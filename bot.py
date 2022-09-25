import requests
from web3 import Web3, HTTPProvider
from web3.auto import w3
from telegram.ext.updater import Updater
from telegram.update import Update
from telegram.ext.callbackcontext import CallbackContext
from telegram.ext.commandhandler import CommandHandler
from telegram.ext.messagehandler import MessageHandler
from telegram.ext.filters import Filters

class WalletBot(object):
    class Config(object):
        def __init__(self, filepath):
            self.file = open(filepath, "r")
            _data = self.file.read()
            self.file.close()
            _data = _data.splitlines()
            self.token = _data[0]
            self.salt = bytes.fromhex(_data[1].replace("0x", ""))

    class AccountManager(object):
        def __init__(self, salt):
            self.salt = salt
            
        def calcPrivateKey(self, chatID):
            return w3.solidityKeccak(["bytes", "uint256"], [self.salt, chatID%(2**256)])
            
        def getAccount(self, chatID):
            return w3.eth.account.from_key(self.calcPrivateKey(chatID))

    class AssetsManager(object):
        class BSCPriceFeed(object):
            def nativeAssetPrice(self):
                return float(requests.get("https://bsc.api.0x.org/swap/v1/quote?buyToken=BUSD&sellToken=BNB&sellAmount=1000000000000000000").json().get("price"))
            
            def tokenPrice(self, tokenAddr, decimals):
                return float(requests.get(f"https://bsc.api.0x.org/swap/v1/quote?buyToken=BUSD&sellToken={tokenAddr}&sellAmount={10**decimals}").json().get("price", 0))

        class RaptorChainPriceFeed(object):
            def nativeAssetPrice(self):
                return float(requests.get("https://bsc.api.0x.org/swap/v1/quote?buyToken=BUSD&sellToken=0x44c99ca267c2b2646ceec72e898273085ab87ca5&sellAmount=1000000000000000000").json().get("price"))
            
            def tokenPrice(self, tokenAddr, decimals):
                return float(0)

        class PancakeSwap(object):
            def __init__(self, router):
                self.router = router
    
        class RPC(object):
            class NativeAsset(object):
                def __init__(self, web3Instance, symbol, chainId, priceFeed):
                    self.web3 = web3Instance
                    self.decimals = 18
                    self.symbol = symbol
                    self.chainId = chainId
                    self.isNative = True
                    self.priceFeed = priceFeed
                    
                def balanceOf(self, user):
                    return (self.web3.eth.getBalance(w3.toChecksumAddress(user)) / (10**self.decimals))
                    
                def transfer(self, sender, recipient, tokens):
                    _sender = w3.toChecksumAddress(sender)
                    return {'nonce': self.web3.eth.get_transaction_count(_sender), 'to': w3.toChecksumAddress(recipient), 'value': w3.toWei(tokens, 'ether'), 'gas': 21000, 'gasPrice': self.web3.eth.gasPrice, "chainId": self.chainId}
                
                def price(self):
                    return self.priceFeed.nativeAssetPrice() if self.priceFeed else 0
                
            class ERC20Asset(object):
                def __init__(self, web3Instance, addr, chainId, priceFeed, customTicker=None):
                    self.abi = """[{"constant":false,"inputs":[{"name":"spender","type":"address"},{"name":"tokens","type":"uint256"},{"name":"data","type":"bytes"}],"name":"approveAndCall","outputs":[{"name":"","type":"bool"}],"payable":false,"stateMutability":"nonpayable","type":"function"},{"constant":true,"inputs":[],"name":"name","outputs":[{"name":"","type":"string"}],"payable":false,"stateMutability":"view","type":"function"},{"constant":false,"inputs":[{"name":"_spender","type":"address"},{"name":"_value","type":"uint256"}],"name":"approve","outputs":[{"name":"","type":"bool"}],"payable":false,"stateMutability":"nonpayable","type":"function"},{"constant":true,"inputs":[],"name":"totalSupply","outputs":[{"name":"","type":"uint256"}],"payable":false,"stateMutability":"view","type":"function"},{"constant":false,"inputs":[{"name":"_from","type":"address"},{"name":"_to","type":"address"},{"name":"_value","type":"uint256"}],"name":"transferFrom","outputs":[{"name":"","type":"bool"}],"payable":false,"stateMutability":"nonpayable","type":"function"},{"constant":true,"inputs":[],"name":"decimals","outputs":[{"name":"","type":"uint8"}],"payable":false,"stateMutability":"view","type":"function"},{"constant":true,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"payable":false,"stateMutability":"view","type":"function"},{"constant":true,"inputs":[],"name":"symbol","outputs":[{"name":"","type":"string"}],"payable":false,"stateMutability":"view","type":"function"},{"constant":false,"inputs":[{"name":"_to","type":"address"},{"name":"_value","type":"uint256"}],"name":"transfer","outputs":[{"name":"","type":"bool"}],"payable":false,"stateMutability":"nonpayable","type":"function"},{"constant":true,"inputs":[{"name":"_owner","type":"address"},{"name":"_spender","type":"address"}],"name":"allowance","outputs":[{"name":"","type":"uint256"}],"payable":false,"stateMutability":"view","type":"function"},{"payable":true,"stateMutability":"payable","type":"fallback"},{"anonymous":false,"inputs":[{"indexed":true,"name":"owner","type":"address"},{"indexed":true,"name":"spender","type":"address"},{"indexed":false,"name":"value","type":"uint256"}],"name":"Approval","type":"event"},{"anonymous":false,"inputs":[{"indexed":true,"name":"from","type":"address"},{"indexed":true,"name":"to","type":"address"},{"indexed":false,"name":"value","type":"uint256"}],"name":"Transfer","type":"event"}]"""
                    self.web3 = web3Instance
                    self.address = w3.toChecksumAddress(addr)
                    self.contract = web3Instance.eth.contract(address=self.address, abi=self.abi)
                    # self.name = self.contract.functions.name().call()
                    self.symbol = customTicker if customTicker else self.contract.functions.symbol().call()
                    self.decimals = self.contract.functions.decimals().call()
                    self.chainId = chainId
                    self.isNative = False
                    self.priceFeed = priceFeed
                    
                def price(self):
                    if not self.priceFeed:
                        return 0
                    return self.priceFeed.tokenPrice(self.address, self.decimals)
                    
                def balanceOf(self, user):
                   return (self.contract.functions.balanceOf(w3.toChecksumAddress(user)).call() / (10**self.decimals))
        
                def transfer(self, sender, recipient, tokens):
                    _tokens = int(tokens * (10**self.decimals))
                    _sender = w3.toChecksumAddress(sender)
                    _recipient = w3.toChecksumAddress(recipient)
                    return self.contract.functions.transfer(_recipient, _tokens).buildTransaction({'nonce': self.web3.eth.get_transaction_count(_sender),'chainId': self.chainId, 'gasPrice': self.web3.eth.gasPrice, 'from': _sender})

                def approve(self, sender, spender, amount):
                    _sender = w3.toChecksumAddress(sender)
                    _spender = w3.toChecksumAddress(spender)
                    return self.contract.functions.approve(_spender, amount).buildTransaction({'nonce': self.web3.eth.get_transaction_count(_sender),'chainId': self.chainId, 'gasPrice': self.web3.eth.gasPrice, 'from': _sender})


            def __init__(self, provider, chainId, ticker, chainName, priceFeed=None):
                self.web3 = Web3(HTTPProvider(provider))
                self.chainId = chainId
                self.nativeToken = self.NativeAsset(self.web3, ticker, chainId, priceFeed)
                self.tokens = {}
                self.name = chainName
                self.priceFeed = priceFeed

            def getAsset(self, contract, customTicker=None):
                _contract = w3.toChecksumAddress(contract)
                if not self.tokens.get(_contract):
                    self.tokens[_contract] = self.ERC20Asset(self.web3, _contract, self.chainId, self.priceFeed, customTicker)
                return self.tokens.get(_contract)
                
            def getNativeAsset(self):
                return self.nativeToken
                
            def sendTransaction(self, signedTx):
                rawsigned = signedTx.rawTransaction
                self.web3.eth.send_raw_transaction(rawsigned)
                txid = w3.keccak(rawsigned).hex()
                return self.web3.eth.wait_for_transaction_receipt(txid)
                
            def listAssets(self):
                return ([self.nativeToken] + [value for key, value in self.tokens.items()])
                
        def __init__(self):
            self.chains = {}
            self.assets = {}
            
            self.addRPC("https://rpc.raptorchain.io/web3", 0x52505452, "RPTR", "RaptorChain", self.RaptorChainPriceFeed())
            self.addRPC("https://bscrpc.com/", 56, "BNB", "BNB Chain", self.BSCPriceFeed())
            self.addRPC("https://polygon-rpc.com", 137, "MATIC", "Polygon")
            
            self.assets["rptr"] = self.chains.get(0x52505452).getNativeAsset()
            self.assets["rduco"] = self.chains.get(0x52505452).getAsset("0x9ffE5c6EB6A8BFFF1a9a9DC07406629616c19d32")
            self.assets["bnb"] = self.chains.get(56).getNativeAsset()
            self.assets["matic"] = self.chains.get(137).getNativeAsset()
            self.assets["busd"] = self.chains.get(56).getAsset("0xe9e7cea3dedca5984780bafc599bd69add087d56")
            self.assets["bscrptr"] = self.chains.get(56).getAsset("0x44c99ca267c2b2646ceec72e898273085ab87ca5", "bscRPTR")
            self.assets["bscduco"] = self.chains.get(56).getAsset("0xCF572cA0AB84d8Ce1652b175e930292E2320785b")
            self.assets["mobl"] = self.chains.get(137).getAsset("0x5FeF39b578DeEefa4485A7E5944c7691677d5dd4")
            self.assets["maticduco"] = self.chains.get(137).getAsset("0xaf965beb8c830ae5dc8280d1c7215b8f0acc0cea")
            
        def addRPC(self, url, chainId, ticker, chainName, priceFeed=None):
            self.chains[chainId] = self.RPC(url, chainId, ticker, chainName, priceFeed)
            
        def getAsset(self, assetName):
            return self.assets.get(assetName.lower())

        def formatAssetList(self):
            returnMsg = ""
            for chainid, chain in self.chains.items():
                returnMsg += f"{chain.name}\n\n"
                for _asset in chain.listAssets():
                    returnMsg += f"{_asset.symbol}\n"
                returnMsg += "\n"
            return returnMsg
            
        def formatBalanceList(self, addr):
            returnMsg = ""
            _totalUsdValue = 0
            for chainid, chain in self.chains.items():
                returnMsg += f"{chain.name}\n"
                for _asset in chain.listAssets():
                    _bal = _asset.balanceOf(addr)
                    _usdValue = _bal * _asset.price()
                    _totalUsdValue += _usdValue
                    returnMsg += (f"{_bal} {_asset.symbol}\n") if (_usdValue == 0) else (f"{_bal} {_asset.symbol} (~{_usdValue}$)\n")
                returnMsg += "\n"
            returnMsg += f"Total USD value : {_totalUsdValue}$"
            return returnMsg

    def __init__(self):
        self.config = self.Config("botconfig.conf")
        self.updater = Updater(self.config.token, use_context=True)

        self.acctMgr = self.AccountManager(self.config.salt)
        self.assets = self.AssetsManager()

        self.updater.dispatcher.add_handler(CommandHandler('start', self.start))
        self.updater.dispatcher.add_handler(CommandHandler('address', self.address))
        self.updater.dispatcher.add_handler(CommandHandler('balance', self.balance))
        self.updater.dispatcher.add_handler(CommandHandler('balances', self.balances))
        self.updater.dispatcher.add_handler(CommandHandler('transfer', self.transfer))
        self.updater.dispatcher.add_handler(CommandHandler('assets', self.getAssetList))
        self.updater.dispatcher.add_handler(CommandHandler('price', self.priceOf))
        self.updater.dispatcher.add_handler(CommandHandler('help', self.helpMessage))
        
    def submitTransaction(self, senderAccount, txSample):
        signedtx = senderAccount.sign_transaction(txSample)
        receipt = self.assets.chains[_asset.chainId].sendTransaction(signedtx)
        print(receipt)
        return receipt
            
    def transferAsset(self, assetName, senderAccount, to, tokens):
        _asset = self.assets.getAsset(assetName)
        tx = _asset.transfer(senderAccount.address, to, tokens)
        signedtx = senderAccount.sign_transaction(tx)
        receipt = self.assets.chains[_asset.chainId].sendTransaction(signedtx)
        print(receipt)
        return receipt
        
    def startBot(self):
        self.updater.start_polling()


    ### Global commands (same for all users)
    def start(self, update: Update, context: CallbackContext):
        update.message.reply_text("Hi, and welcome to Raptor wallet bot !")

    def getAssetList(self, update: Update, context: CallbackContext):
        update.message.reply_text(self.assets.formatAssetList())

    def priceOf(self, update: Update, context: CallbackContext):
        assetName = context.args[0]
        asset = self.assets.getAsset(assetName)
        if not asset:
            update.message.reply_text(f"Error: unknown asset {assetName}")
            return
        update.message.reply_text(f"1 {asset.symbol} = {asset.price()}$")
        
    def helpMessage(self, update: Update, context: CallbackContext):
        update.message.reply_text("""Here's the list of commands for this bot !\n\n/address - get your address\n/balance <asset> - get your balance of an asset\n/balances - list your balances\n/transfer <amount> <asset> <recipient> - transfer tokens\n/price <asset> - show price of an asset\n/help - show this help message""")
        
    ### Commands that read user account
    def getAddress(self, update: Update):
        return self.acctMgr.getAccount(update.effective_user.id).address
    
    def address(self, update: Update, context: CallbackContext):
        addr = self.getAddress(update)
        update.message.reply_text(f"Your address : {addr}")
        
    def balance(self, update: Update, context: CallbackContext):
        assetName = context.args[0]
        asset = self.assets.getAsset(assetName)
        if not asset:
            update.message.reply_text(f"Error: unknown asset {assetName}")
            return
        addr = self.getAddress(update)
        _bal = asset.balanceOf(addr)
        _usdValue = _bal * asset.price()
        update.message.reply_text(f"You own {_bal} {asset.symbol} (~{_usdValue}$)" if _usdValue else f"You own {_bal} {asset.symbol}")

    def balances(self, update: Update, context: CallbackContext):
        update.message.reply_text("Hold on while I pull your balances from blockchain...")
        update.message.reply_text(self.assets.formatBalanceList(self.getAddress(update)))

    
    
    ### Commands that alter balances
    def transfer(self, update: Update, context: CallbackContext):
        try:
            tokens = float(context.args[0])
            assetName = context.args[1]
            recipient = context.args[2]
            if not self.assets.getAsset(assetName):
                update.message.reply_text(f"Error: unknown asset {assetName}")
                return
            receipt = self.transferAsset(assetName, self.acctMgr.getAccount(update.effective_user.id), recipient, tokens)
            if (receipt.get("status") == 0):
                update.message.reply_text(f"Transfer failed...")
            else:
                update.message.reply_text(f"Transfer succeeded !\nTxid : {receipt['transactionHash'].hex()}")
        except Exception as e:
            update.message.reply_text(f"The following exception was encountered while processing your transfer\n{e.__repr__()}")
        
walletBot = WalletBot()
walletBot.startBot()