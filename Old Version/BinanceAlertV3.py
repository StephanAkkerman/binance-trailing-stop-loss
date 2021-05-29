#!/usr/bin/python3
# New in V3: TA Long and short signals
from binance.client import Client
from binance.websockets import BinanceSocketManager
from binance.enums import *
import talib as ta  #Used for Technical Analysis (TA)
import numpy as np  #Used for converting a list to a numpy array, which is then used for talib
import datetime     #Used for converting time to string
import requests     #Used for telegram messages
import threading    #Used for scheduling tasks not handled by the websocket
import math         #Used for calculating the precision for making orders
import time         #Used for time.sleep
import traceback    #Used for debugging
import os           #Used for exiting the code, necessary for RaspberryPi restart

#Max 1200 requests per minute; 10 orders per second; 100,000 orders per 24hrs

# !!! Fill these values in on line 589 as well !!!
client = Client(api_key = 'publicKey', api_secret = 'privateKey')

# To make sure you do not exceed the max request, make a new Binance account for more API calls
altClient = Client(api_key = 'publicKey', api_secret = 'privateKey')

#A single connection can listen to a maximum of 1024 streams.
#WebSocket connections have a limit of 5 incoming messages per second
bm = BinanceSocketManager(client)

##########################################################
######### CODE FOR SENDING THE TELEGRAM MESSAGES #########
##########################################################

def sendBuyAlert(bot_message):
    tijd = datetime.datetime.now().strftime("%H:%M:%S")
    pMsg = bot_message.replace("%2B", "+")  #For displaying in console
    pMsg = pMsg.replace("%25", "%")         #For displaying in console
    print(" ".join([pMsg, "at", tijd]))

    # https://medium.com/@ManHay_Hong/how-to-create-a-telegram-bot-and-send-messages-with-python-4cf314d9fa3e
    # Follow the above the tutorial to get your Telegram API keys
    bot_token = 'bot_token'
    sendTo = ['id']
    for receiver in sendTo:
        send_text = 'https://api.telegram.org/bot' + bot_token + '/sendMessage?chat_id=' + receiver + '&parse_mode=HTML&text=' + bot_message
        response = requests.get(send_text)

def sendSellAlert(bot_message):
    tijd = datetime.datetime.now().strftime("%H:%M:%S")
    pMsg = bot_message.replace("%25", "%")  #For displaying in console
    print(" ".join([pMsg, "at", tijd]))
    
    bot_token = 'bot_token2'
    sendTo = ['id']
    for receiver in sendTo:
        send_text = 'https://api.telegram.org/bot' + bot_token + '/sendMessage?chat_id=' + receiver + '&parse_mode=HTML&text=' + bot_message
        response = requests.get(send_text)

###################################################
######### CODE FOR THE TRAILING STOP LOSS #########
###################################################

#Returns quantity of asset, necessary for creating an order
def getQuantity(sym): 
    #Remove USDT
    sym = sym[:-4]
    assets = (client.get_account()).get('balances')
    for asset in assets:
        if asset['asset'] == sym:
            return (float(asset.get('free')) + float(asset.get('locked'))) * 0.995
   
def trailingStopLoss(sym, close):
    #Get original price, which is the latest trade
    #Most recent trade in this coin should be a buy order
    #Might run into problems if we sell half of it, might want to use 'isBuyer' : True
    trades = client.get_my_trades(symbol = sym)
    originalPrice = float(trades[-1]['price'])
    originalID = trades[-1]['orderId']
    
    #If the last trade is a sell order, then remove from owned, assuming everything is sold
    if trades[-1]['isBuyer'] == False:
        ownedList.remove(sym)
        return

    #Gets the orderId of open orders, also gets the last stop price
    openOrder = client.get_open_orders(symbol= sym)

    #If there is no open order, do nothing (could be replaced by making a stop-loss)
    if not openOrder:
        #Code for making a stop-loss
        #Use info in trades[-1]
        return  

    #If the new close is bigger than the price we bought at, change the stop-loss
    if close > originalPrice:
        
        #Get the info of the old order, which needs to be cancelled
        #Oldest order will be the latest openOrder
        oldStop = float(openOrder[0]['stopPrice'])
        openId = openOrder[0]['orderId']

        #Calculate the original stop price percentage
        allOrders = client.get_all_orders(symbol = sym)

        difference = 9223372036854775807
        originalStopPrice = 0

        #Find the order that is closest to the buy order, assuming a stop loss is made after buying 
        for order in allOrders:
            orderID = order['orderId']
            if orderID > originalID:
                if orderID - originalID < difference:
                    difference = orderID - originalID 
                    originalStopPrice = float(order['price'])

        #Calculate the old stop percentage
        #Will be 1 - (95 - 100) / 100 = 0.95
        stopPercentage = 1 + (originalStopPrice - originalPrice) / originalPrice

        #necessary for determining if we cancel the order or not
        #uses the same method for determining right quantity
        tickSize = float(client.get_symbol_info(sym)["filters"][0].get("tickSize"))
        afrond = int(round(-math.log (tickSize, 10), 0))

        #Set a stop loss at stopPercentage below the current price 
        #Round it, otherwise it might not be allowed to use
        newStop = round(close * stopPercentage, afrond) 

        #If new stop price is higher than the old one, cancel old stop loss
        if newStop > oldStop:
            #Cancel old stop loss order, needs that order id
            #For some reason this sometimes doesn't work and gives error:
            #binance.exceptions.BinanceAPIException: APIError(code=-2011): Unknown order sent.
            try:
                client.cancel_order(symbol = sym, orderId = openId) 
            except Exception as e:
                print(e)

            #Send update if newStop is higher then oldStop and it's higher than originalPrice
            if newStop > originalPrice:
                sendUpdate(sym, newStop, originalPrice, getQuantity(sym))

        #if new stop would be lower than the old one, exit function here
        else:
            return 

        #if no stop-loss exists or new stop is higer than old one, make new stop loss order
        #Limit price is the stop price but 1% smaller
        prijs = round(newStop * 0.99, afrond) 

        stepSize = float(client.get_symbol_info(sym)["filters"][2].get("stepSize"))
        precision = int(round(-math.log(stepSize, 10), 0))
        quant = round(getQuantity(sym), precision)

        try:
            client.create_order(symbol = sym, side = "SELL", type = "STOP_LOSS_LIMIT", quantity = quant, stopPrice = newStop, price = prijs, timeInForce = "GTC")
            msg = " ".join(["STOP_LOSS_LIMIT", sym, "$" + str(close), str(newStop), str(prijs), "stop %", str(stopPercentage)])
            print(msg)
        #If an error occurs, probably APIError(code=-1013): Filter failure: PRICE_FILTER round everything to 2
        except Exception as e: 
            print(e)           
            msg = " ".join(["Error!, Tried:","STOP_LOSS_LIMIT", sym, "$" + str(close), str(newStop), str(prijs), "stop %", str(stopPercentage)])
            print(msg)       

#This part is specific for updates on trailing stop loss
updatesList = []
def sendUpdate(sym, newPrice, original, quantity):
    if sym not in updatesList:
        newPrice = round(newPrice, 2)
        original = round(original, 2)

        diff = newPrice - float(original)
        total = diff * quantity
        total = round(total, 2)

        msg = " ".join(["Profit with Stop Loss", sym, "total in $", str(total), str(newPrice), str(original)])
        sendSellAlert(msg)
        updatesList.append(sym)

########################################################
#########  CODE THAT USES THE WEBSOCKETS DATA  #########
########################################################

#List to keep track of messages that were already sent
MACDSellMsg = []
MACDBuyMsg = []
BBBuyMsg = []
BBSellMsg = []
ATHMsg = []
ATLMsg = []

#Messages for S/R
NearSTSupportMsg = [] 
NearLTSupportMsg = [] 

LostSTSupportMSG = []
LostLTSupportMSG = []

NearSTResistanceMsg = []
NearLTResistanceMsg = []

BrokeSTResistanceMsg = []
BrokeLTResistanceMsg = []

#Not implemented
BounceOfSTSupportMsg = []
BounceOfLTSupportMsg = []

#Used in start_symbol_ticker_socket
def get1dCandles(data):
    try:
        #Symbol as string, for instance "BTCUSDT"
        sym = data["s"]

        #Current close value of the 1d candle
        close = float(data["k"]["c"])
    
        #Current high and lows of this 1d candle
        high = float(data["k"]["h"])
        low = float(data["k"]["l"])

        #If the symbol that is being checked is owned
        if sym in ownedList:
            #Set a trailing stop loss
            trailingStopLoss(sym, close)

###################################################
#########  CODE IF THERE IS A DAILY HIGH  #########
###################################################

        if close == high:  
            #Do this for every coin
            TAInfo = TADict.get(sym)
                
            #Code for losing support or breaking resistance
            #If the current price is higher than that resistance 
            #Send a message and change the resistance
            #Do the same for support
            STSupp = TAInfo[3]
            STRess = TAInfo[4] 
            LTSupp = TAInfo[5] 
            LTRess = TAInfo[6] 

            nearSTRess = STRess * 0.99
            nearLTREss = LTRess * 0.99

            SRInfo = "\nST S/R " + str(STSupp) + " - " + str(STRess)
            SRInfo = SRInfo + "\nLT S/R " + str(LTSupp) + " - " + str(LTRess)

            if close > nearLTREss:
                if close > LTRess:

                    updateSuppRess(sym, close)
                    TAInfo = TADict.get(sym)
                    LTRess = TAInfo[6]

                    if sym not in BrokeLTResistanceMsg:
                        msg = " ".join(["Broke LT Resistance", sym, "$" + str(close), SRInfo, "\nNew LT Resistance:", str(LTRess)])
                        BrokeLTResistanceMsg.append(sym)
                        sendBuyAlert(msg)
                else:
                    if sym not in NearLTResistanceMsg:
                        if sym in ownedList or sym in shortList:
                            msg = " ".join(["Near LT Resistance", sym, "$" + str(close), SRInfo])
                            NearLTResistanceMsg.append(sym)
                            if sym in ownedList:
                                sendSellAlert(msg)
                            elif sym in shortList:
                                sendBuyAlert(msg)

            elif close > nearSTRess:
                #Broke ress
                if close > STRess:

                    updateSuppRess(sym, close)
                    TAInfo = TADict.get(sym)
                    STRess = TAInfo[4]

                    if sym not in BrokeSTResistanceMsg:
                        msg = " ".join(["Broke 1d Resistance", sym, "$" + str(close), SRInfo,"\nNew ST Resistance:", str(LTRess) ])
                        BrokeSTResistanceMsg.append(sym)
                        sendBuyAlert(msg)
                else:
                    #near ress
                    if sym not in NearSTResistanceMsg:
                        if sym in ownedList or sym in shortList:
                            msg = " ".join(["Near 1d Resistance", sym, "$" + str(close), SRInfo])
                            NearSTResistanceMsg.append(sym)
                            if sym in ownedList:
                                sendSellAlert(msg)
                            elif sym in shortList:
                                sendBuyAlert(msg)      

                

            #Do this in case we own it or it is shortable
            #Also check if it is not already in one of the MSG lists
            if sym in ownedList or sym in shortList:                 

                if sym not in MACDBuyMsg or sym not in MACDSellMsg:

                    fourHourData = client.get_klines(symbol = sym, interval = Client.KLINE_INTERVAL_4HOUR)[-60:]
                    closeList = [float(item[4]) for item in fourHourData] 
                    closeArr = np.array(closeList)
                    macd, macdsignal, macdhist = ta.MACD(closeArr) 

                    #Round MACD to precision of price
                    tickSize = (client.get_symbol_info(sym)["filters"][0].get("tickSize"))
                    precision = int(round(-math.log(float(tickSize), 10), 0))
                    MACDNow = round(macdhist[-1], precision)
                    MACD4h = round(macdhist[-2], precision)
                    MACD8h = round(macdhist[-3], precision)

                    #From negative hist to positive
                    if MACDNow > 0 and MACD4h < 0:
                        if sym not in MACDBuyMsg:
                            info = " ".join(["Bullish MACD Cross, last 3 4h candles:", str(MACD8h), str(MACD4h), str(MACDNow)])

                            #Send Buy Message
                            msg = " ".join(["Long", sym, "$" + str(close), info])
                            sendBuyAlert(msg) 

                            #Append to list
                            MACDBuyMsg.append(sym)
                    
                    #Bearish MACD Cross: from positive hist to negative
                    if MACDNow < 0 and MACD4h > 0:
                        if sym not in MACDSellMsg:
                            info = " ".join(["Bearish MACD Cross, last 3 4h candles:", str(MACD8h), str(MACD4h), str(MACDNow)])

                            #Send a msg based on the coin
                            if sym in ownedList:
                                msg = " ".join(["Sell", sym, "$" + str(close), info])
                                sendSellAlert(msg)

                            elif sym in shortList:
                                msg = " ".join(["Short", sym, "$" + str(close), info])
                                sendBuyAlert(msg) 

                            #Append to list
                            MACDSellMsg.append(sym)

                if sym not in BBSellMsg:
                    BBList = TAInfo[0]
                    upper = BBList[2]

                    if close > upper:
                        #Calculate how much percent the close is over the upper band
                        over = close - upper
                        overPercentage = over / upper * 100

                        #Calculate the RSI and MACD
                        fourHourData = client.get_klines(symbol = sym, interval = Client.KLINE_INTERVAL_4HOUR)[-60:]
                        closeList = [float(item[4]) for item in fourHourData] 
                        closeArr = np.array(closeList)
                        macd, macdsignal, macdhist = ta.MACD(closeArr) 
                        latestRSI = ta.RSI(closeArr)[-1] 
                    
                        #Round everything to two decimals
                        BBInfo = round(overPercentage, 2)
                        RSIInfo = round(latestRSI, 2)

                        #Round MACD to precision of price
                        tickSize = (client.get_symbol_info(sym)["filters"][0].get("tickSize"))
                        precision = int(round(-math.log(float(tickSize), 10), 0))
                        MACDInfo = round(macdhist[-1], precision)

                        #If the RSI is bigger than 70 & at the upper BB
                        if latestRSI >= 70:
                            info = "\n" + str(BBInfo) + "%25 over UPPER BB"
                            info = info + "\nRSI: " + str(RSIInfo)
                            info = info + "\nMACD Hist: " + str(MACDInfo)
                            info = info + "\nST S/R: " + str(STSupp) + " - " + str(STRess)
                            info = info + "\nLT S/R: " + str(LTSupp) + " - " + str(LTRess)

                            #Send a msg based on the coin
                            if sym in ownedList:
                                msg = " ".join(["Sell", sym, "$" + str(close), info])
                                sendSellAlert(msg) 
                                
                            elif sym in shortList:
                                msg = " ".join(["Short", sym, "$" + str(close), info])
                                sendBuyAlert(msg)

                            #Append to list
                            BBSellMsg.append(sym)

            #Sends a message if an All Time High (ATH) has been reached for any coin, otherwise it's a waste of time
            if sym not in ATHMsg: 
                #len of months is 2, 0 and 1
                monthsData = client.get_klines(symbol = sym, interval = Client.KLINE_INTERVAL_1MONTH) 
                monthsHigh = -1 #in case it just got listed
              
                for month in range (0,len(monthsData)): 
                    if high >= float(monthsData[-month][2]): 
                        monthsHigh = month + 1 #Because range(0,1) is only checking 0
                    #We only want them if they are back to back, so break if its <
                    else: 
                        break

                if monthsHigh == len(monthsData): #+1 since lists starts at 0
                    msg = " ".join(["ALL TIME HIGH!", sym, "$", str(close)])
                    sendBuyAlert(msg) 

                    #Append to list
                    ATHMsg.append(sym)

##################################################
#########  CODE IF THERE IS A DAILY LOW  #########
##################################################

        if close == low:                
            TAInfo = TADict.get(sym)

            #Code for bounce of support or losing support
            #Near when it's less than 1% away, maybe bigger?
            STSupp = TAInfo[3]
            STRess = TAInfo[4] 
            LTSupp = TAInfo[5] 
            LTRess = TAInfo[6] 

            nearSTSupp = STSupp * 1.01
            nearLTSupp = LTSupp * 1.01

            SRInfo = "\nST S/R " + str(STSupp) + " - " + str(STRess)
            SRInfo = SRInfo + "\nLT S/R " + str(LTSupp) + " - " + str(LTRess)

            if close < nearLTSupp:
                if close > LTSupp:
                    if sym not in NearLTSupportMsg:
                        msg = " ".join(["Near LT Support", sym, "$" + str(close), SRInfo])
                        NearLTSupportMsg.append(sym)
                        sendBuyAlert(msg)

                else:

                    updateSuppRess(sym, close)
                    TAInfo = TADict.get(sym)
                    LTSupp = TAInfo[5] 

                    if sym not in LostLTSupportMSG:
                        if sym in ownedList or sym in shortList:
                            msg = " ".join(["Lost LT Support", sym, "$" + str(close), SRInfo, "\nNew LT Support:", str(LTSupp)])
                            LostLTSupportMSG.append(sym)
                            if sym in ownedList:
                                sendSellAlert(msg)
                            elif sym in shortList:
                                sendBuyAlert(msg)                         
                
            elif close < nearSTSupp:
                if close > STSupp:
                    #Near supp
                    if sym not in NearSTSupportMsg:
                        msg = " ".join(["Near 1d Support", sym, "$" + str(close), SRInfo])
                        NearSTSupportMsg.append(sym)
                        sendBuyAlert(msg)

                else:
                    #Lost supp

                    updateSuppRess(sym, close)
                    TAInfo = TADict.get(sym)
                    STSupp = TAInfo[3]

                    if sym not in LostSTSupportMSG:
                        if sym in ownedList or sym in shortList:
                            msg = " ".join(["Lost 1d Support", sym, "$" + str(close), SRInfo, "\nNew ST Support:", str(STSupp)])
                            LostSTSupportMSG.append(sym)
                            if sym in ownedList:
                                sendSellAlert(msg)
                            elif sym in shortList:
                                sendBuyAlert(msg)      

            if sym not in MACDBuyMsg or sym not in MACDSellMsg:

                fourHourData = client.get_klines(symbol = sym, interval = Client.KLINE_INTERVAL_4HOUR)[-60:]
                closeList = [float(item[4]) for item in fourHourData] 
                closeArr = np.array(closeList)
                macd, macdsignal, macdhist = ta.MACD(closeArr) 

                #Round MACD to precision of price
                tickSize = (client.get_symbol_info(sym)["filters"][0].get("tickSize"))
                precision = int(round(-math.log(float(tickSize), 10), 0))
                MACDNow = round(macdhist[-1], precision)
                MACD4h = round(macdhist[-2], precision)
                MACD8h = round(macdhist[-3], precision)

                #From negative hist to positive
                if MACDNow > 0 and MACD4h < 0:
                    if sym not in MACDBuyMsg:
                        info = " ".join(["Bullish MACD Cross, last 3 4h candles:", str(MACD8h), str(MACD4h), str(MACDNow)])

                        #Send Buy Message
                        msg = " ".join(["Long", sym, "$" + str(close), info])
                        sendBuyAlert(msg) 

                        #Append to list
                        MACDBuyMsg.append(sym)
                    
                #Bearish MACD Cross: from positive hist to negative
                if MACDNow < 0 and MACD4h > 0:
                    if sym not in MACDSellMsg:
                        info = " ".join(["Bearish MACD Cross, last 3 4h candles:", str(MACD8h), str(MACD4h), str(MACDNow)])

                        #Send a msg based on the coin
                        if sym in ownedList:
                            msg = " ".join(["Sell", sym, "$" + str(close), info])
                            sendSellAlert(msg)

                        elif sym in shortList:
                            msg = " ".join(["Short", sym, "$" + str(close), info])
                            sendBuyAlert(msg) 

                        #Append to list
                        MACDSellMsg.append(sym)

            if sym not in BBBuyMsg:
                BBList = TAInfo[0]
                lower = BBList[0]
            
                if close < lower:
                    #Calculate how much percent the close is under the lower band
                    under = lower - close
                    underPercentage = under / lower * 100
                
                    #Calculate the RSI and MACD
                    fourHourData = client.get_klines(symbol = sym, interval = Client.KLINE_INTERVAL_4HOUR)[-60:]
                    closeList = [float(item[4]) for item in fourHourData] 
                    closeArr = np.array(closeList)
                    macd, macdsignal, macdhist = ta.MACD(closeArr) 
                    latestRSI = ta.RSI(closeArr)[-1] 

                    #Round everything to two decimals
                    BBInfo = round(underPercentage, 2)
                    RSIInfo = round(latestRSI, 2)

                    #Round MACD to precision of price
                    tickSize = (client.get_symbol_info(sym)["filters"][0].get("tickSize"))
                    precision = int(round(-math.log(float(tickSize), 10), 0))
                    MACDInfo = round(macdhist[-1], precision)

                    #If the RSI is lower than 30 & at the lower BB
                    if latestRSI <= 30:
                        info = "\n" + str(BBInfo) + "%25 under LOWER BB"
                        info = info + "\nRSI: " + str(RSIInfo)
                        info = info + "\nMACD Hist: " + str(MACDInfo)
                        info = info + "\nST S/R: " + str(STSupp) + " - " + str(STRess)
                        info = info + "\nLT S/R: " + str(LTSupp) + " - " + str(LTRess)

                        #Send a buy message
                        msg = " ".join(["Long", sym, "$" + str(close), info])
                        sendBuyAlert(msg) 

                        #Append to list
                        BBBuyMsg.append(sym)

            #This is calculated for every coin         
            #Make sure it is not in ATLList otherwise it's not necessary to check
            if sym not in ATLMsg:     
                monthsData = client.get_klines(symbol = sym, interval = Client.KLINE_INTERVAL_1MONTH) 
                monthsLow = -1

                for month in range (0,len(monthsData)): 
                    if low <= float(monthsData[-month][3]): 
                        monthsLow = month + 1
                    #We only want them if they are back to back, so break if its >
                    else: 
                        break

                if monthsLow == len(monthsData): #+1 since lists starts at 0
                    msg = " ".join(["ALL TIME LOW!", sym, "$", str(close)])
                    sendBuyAlert(msg)

                    #Append to list
                    ATLMsg.append(sym)

    #Catch any exception
    except Exception as e: 
        #Print out all the error information
        print(e)
        print(traceback.format_exc())
        #Print the symbol
        print(sym)

        #Wait 1 min before retrying
        print("retrying in 60 sec")
        time.sleep(60) 

        print("retrying...")

        #Refresh client
        refresh()

def refresh():
        client = Client(api_key = 'publicKey', api_secret = 'privateKey')
        altClient = Client(api_key = 'publicKey', api_secret = 'privateKey')

##########################################
#########  CODE FOR WEBSOCKETS  ##########
##########################################

#Uses userSocket info 
#Adds asset to socket if it has been bought
#Sends message if an order has been filled
def userInfo(info):
    operation = info.get('e')

    #Other operations are balanceUpdate and outboundAccountInfo
    if operation == 'executionReport':
        sym = info.get('s')          #ie 'YFIUSDT'

        quant = info.get('q')
        execQuant = info.get('z')    #The cumulative filled quantity

        price = info.get('p')
        execPrice = info.get('L')    #The latest price it was filled at

        side =  info.get('S')        #ie BUY
        orderType =  info.get('o')   #ie LIMIT
        execType =  info.get('x')    #only TRADE important

        #Send alerts to see if we made profit or loss
        if execType == "TRADE":
            #Round to 4 decimals, otherwise we get 8 zeros after .
            msgPrice = round(float(execPrice),4)
            msgQ = round(float(quant), 4)

            if side == "BUY":
                ownedList.append(sym)
                TACalculations(sym)
             
                bm.start_kline_socket(sym, get1dCandles, interval=KLINE_INTERVAL_1DAY)                 
                
                msg = " ".join(["Bought", sym, "$" + str(msgPrice), "Quantity:", str(msgQ)])
                sendSellAlert(msg) 

            if side == "SELL":
                msg = " ".join(["Sold", sym, "$" + str(msgPrice), "Quantity:", str(msgQ)])
                sendSellAlert(msg) 

#Returns a list of all symbols that are currently owned with a value higher than $10, so that its tradable
#Only used at start
ownedList = []
def getOwnedList():
    assets = (client.get_account()).get('balances')
    for asset in assets:
        sym = asset.get('asset')
        available = float(asset.get('free')) + float(asset.get('locked'))
        #If free and locked are bigger than 0.001, because if a coin is $10.000 * 0.001 = $10
        if available > 0.001 :
            if sym != 'USDT' and sym != 'SALT':
                symUSDT = sym + 'USDT'               
                #get_symbol_ticker has less information than get_ticker 
                try:
                    if available * float(client.get_symbol_ticker(symbol = symUSDT)['price']) > 10: #Crashes here if you do anything that ends with something else than USDT
                        ownedList.append(symUSDT)
                        TACalculations(symUSDT)

                        bm.start_kline_socket(symUSDT, get1dCandles, interval=KLINE_INTERVAL_1DAY) 
                        print(symUSDT, end =" ") 

                except Exception as e: 
                    #Print out all the error information
                    print(e)
                    print(traceback.format_exc())
                    print("Crashed in getOwnedList() at symbol:")
                    print(symUSDT)

#Returns a list of all symbols with a market cap higher than 5 million in the last 24 hours
#At the end start the sockets
shortList = []
def startSockets(): #Takes 55 seconds
    #Make call to getOwnedList to fill ownedList
    getOwnedList()

    #List of stable coins often in the 5 mil 24h volume
    stableCoins = ["USDCUSDT", "BUSDUSDT", "TUSDUSDT", "PAXUSDT", "EURUSDT", "GBPUSDT"] 

    counter = 0

    symbols = client.get_exchange_info().get("symbols")
    for syms in symbols:
        #Whole symbol name
        sym = (syms.get("symbol"))
        #We only want symbols ending in USDT
        if sym[-4:] == 'USDT': 
            if sym not in stableCoins:
                #Leveraged are the coins that end with DOWN or UP
                if "SPOT" in syms.get("permissions") and sym not in ownedList:
                        tickerData = client.get_ticker(symbol = sym)
                        #Then calculate if their volume is bigger than 5 million $
                        if float(tickerData['volume']) * float(tickerData['lastPrice']) > 5000000:
                            TACalculations(sym)

                            bm.start_kline_socket(sym, get1dCandles, interval=KLINE_INTERVAL_1DAY) 
                            print(sym, end =" ") 
                            counter = counter + 1

        #Currently disabled to prevent spam

        #Put the DOWNUSDT coins in a list, so we know which coins are shortable
        #Symbol is always a leveraged if it ends with DOWNUSDT
        #if sym[-8:] == 'DOWNUSDT':
            #Remove the DOWN part of the coin
        #    symUSDT = sym.replace("DOWN", "")
        #    shortList.append(symUSDT)
    
    #Start when everything is added
    #This is just for statistics
    counter = counter + len(ownedList)
    print()
    print("Total symbols: " + str(counter))

    bm.start()

###############################################################
#########  CODE FOR TECHNICAL ANALYSIS AT THE START  ##########
###############################################################

def updateSuppRess(sym, close):
    TAInfo = TADict.get(sym)

    #We need all of these to update Dict
    BBList = TAInfo[0]
    STLevels = TAInfo[1]
    LTLevels = TAInfo[2]

    #Code for bounce of support or losing support
    #Near when it's less than 1% away, maybe bigger?
    STSupp = TAInfo[3]
    STRess = TAInfo[4] 
    LTSupp = TAInfo[5] 
    LTRess = TAInfo[6] 

    #Update support
    if close < STSupp:
        for supp in STLevels:
            if supp < close:
                if supp > STSupp:
                    STSupp = supp

    if close < LTSupp:
        for supp in LTLevels:
            if supp < close:
                if supp > LTSupp:
                    LTSupp = supp

    #Update resistance
    if close > STRess:
        for resistance in STLevels:
            if resistance > close:
                if resistance < STRess:
                    STRess = resistance

    if close > LTRess:
        for resistance in LTLevels:
            if resistance > close:
                if resistance < LTRess:
                    LTRess = resistance

    #Update the Dictionary with the new values
    TAList = [BBList, STLevels, LTLevels, STSupp, STRess, LTSupp, LTRess]
    TADict[sym] = TAList

#Makes dictionary of all TA values of a symbol, that can be calculated beforehand
#Currently contains:
#[0] Bolling Bands
#[1] Support and Resistance (Short term)
#[2] Support and Resistance (Long term)
#[3] Current ST Support
#[4] Current ST Resistance
#[5] Current LT Support
#[6] Current LT Resistance
TADict = {}
def TACalculations(sym):
    #More candles = more accurate
    # Use 4H only for Bollinger, MACD and RSI
    fourHourData = client.get_klines(symbol = sym, interval = Client.KLINE_INTERVAL_4HOUR) 

    # Use these for support and resistance
    # One for daily
    dailyData = client.get_klines(symbol = sym, interval = Client.KLINE_INTERVAL_1DAY) 
    # One for long term, weekly and montly combined
    weeklyData = client.get_klines(symbol = sym, interval = Client.KLINE_INTERVAL_1WEEK)
    monthlyData = client.get_klines(symbol = sym, interval = Client.KLINE_INTERVAL_1MONTH)

    #Add 0, in case there is a new coin listing
    #Add 999.999 at the end
    STLevels = [0] + levelsCalculation(dailyData) + [999999]
    LTLevels = [0] + levelsCalculation(weeklyData + monthlyData) + [999999]

    #Return the current levels it is trading at, as close to current price
    #Could be any followed by [-1]
    close = float(fourHourData[-1][4])  

    #[0] will be the lowest and [-1] the highest
    STSupp = STLevels[0]
    STRess = STLevels[-1]

    #Support
    for supp in STLevels:
        if supp < close:
            if supp > STSupp:
                STSupp = supp

    #Resistance
    for resistance in STLevels:
        if resistance > close:
            if resistance < STRess:
                STRess = resistance


    LTSupp = LTLevels[0]
    LTRess = LTLevels[-1]

    for supp in LTLevels:
        if supp < close:
            if supp > LTSupp:
                LTSupp = supp

    for resistance in LTLevels:
        if resistance > close:
            if resistance < LTRess:
                LTRess = resistance

    #Code for Bollinger Bands
    closeList = [float(item[4]) for item in fourHourData] 
    closeArr = np.array(closeList)
    closeArr = np.array(closeList)
    #Bollinger Bands as depicted in tradingview
    upper, middle, lower = ta.BBANDS(closeArr, timeperiod = 20) 
    #Convert mulitple values to list
    BBList = [upper[-1], middle[-1], lower[-1]]

    #Make a new list of these values
    TAList = [BBList, STLevels, LTLevels, STSupp, STRess, LTSupp, LTRess]

    #Store all values in dictionary, as {sym : [[TA]]}
    TADict[sym] = TAList

#Code for Support and Resistance
def levelsCalculation(data):   
   
    highList = [float(item[2]) for item in data]
    lowList = [float(item[3]) for item in data]

    #Reverse them so the most recent dates are at the front
    highList.reverse()
    lowList.reverse()

    #Calculate the mean difference
    s =  np.mean(highList) - np.mean(lowList)

    #Instead of doing support and resistance do both in one list
    #Reason being that passed resistance becomes support and vice versa
    keyLevels = []

    for day in range(2,len(data)-2):
        if lowList[day] < lowList[day-1] and lowList[day] < lowList[day+1] and lowList[day+1] < lowList[day+2] and lowList[day-1] < lowList[day-2]:
            if np.sum([abs(lowList[day]-x) < s for x in keyLevels]) == 0:
                keyLevels.append(lowList[day])

        if highList[day] > highList[day-1] and highList[day] > highList[day+1] and highList[day+1] > highList[day+2] and highList[day-1] > highList[day-2]:
            if np.sum([abs(highList[day]-x) < s for x in keyLevels]) == 0:
                keyLevels.append(highList[day])

    keyLevels.sort()

    return (keyLevels)

############################################
#########  CODE FOR NEW LISTINGS  ##########
############################################

#This is necessary for newListings
oldSymbols = client.get_exchange_info().get("symbols")
    
#Checks if there a new listings and buys if its a USDT pair
#Sends a message if that is not the case
def newListings():  
    try:
        #Use the global oldSymbols
        global oldSymbols

        currentSymbols = altClient.get_exchange_info().get("symbols")
    
        #If symbols get removed, refresh oldSymbols
        if len(currentSymbols) < len(oldSymbols):
        
            #Refresh if symbols get deleted
            oldSymbols = client.get_exchange_info().get("symbols")

        #If there are new listings, currentLen will be larger
        #The new listings will always be at the end of the list of dicts
        if len(currentSymbols) > len(oldSymbols):     
            diff = len(currentSymbols) - len(oldSymbols)

            #Get the last new listings
            newSymbols = currentSymbols[-diff:]

            #Refresh oldSymbols so we wont get an infinite loop
            oldSymbols = client.get_exchange_info().get("symbols")

            #Buy the spot USDT-pair at market value
            for syms in newSymbols:
                sym = (syms.get("symbol"))

                if "SPOT" in syms.get("permissions"): 
                    #Always send a message in case of a spot listing
                    sendBuyAlert("New SPOT Listing: " + sym)

        #Check every 60 seconds using AltClient to check for changes
        #Regular client is used for the other operations
        threading.Timer(60, newListings).start()

    except Exception as e: 
        #Print out all the error information
        print(e)
        print(traceback.format_exc())

        #Wait 1 min before retrying
        print("retrying in 60 sec")
        time.sleep(60) 

        print("retrying...")

        #Refresh client
        refresh()


#######################################
#########  CODE FOR RUNNING  ##########
#######################################

#2. Initialize connect using the 1m candles
#The data get sends to get1dCandles
def start():
    tijd = datetime.datetime.now().strftime("%H:%M:%S")
    print("Starting at " + tijd)
    
    newListings()
    bm.start_user_socket(userInfo)
    startSockets()

    tijd = datetime.datetime.now().strftime("%H:%M:%S")
    print("Sockets started at " + tijd)

    #After 4 hours (14400) restart, using the new >5 mil market cap coins
    #After 1 hour (3600) restart
    
    #time.sleep(3480)
    #2 min before closing the open, start a new one, so sockets dont have to load
    #os.system("python3 BinanceAlertV3.py")
    #time.sleep(120)

    time.sleep(3600)

    tijd = datetime.datetime.now().strftime("%H:%M:%S")
    print("Stopped at " + tijd)
    os._exit(0) 

    #bm.start_symbol_ticker_socket(sym, get24hCandles) gives more info

#1. Start the code
if __name__ == '__main__':
    start()