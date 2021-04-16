#!/usr/bin/python3
from binance.client import Client
from binance.websockets import BinanceSocketManager
from binance.enums import *
import datetime     # Used for converting time to string
import math         # Used for calculating the precision for making orders
import time         # Used for time.sleep
import traceback    # Used for debugging
import os           # Used for exiting the code, necessary for RaspberryPi restart
import pandas as pd # Used for handling dictionaries and lists

# Max 1200 requests per minute; 10 orders per second; 100,000 orders per 24hrs
public_key = 'YOUR_PUBLIC_KEY'
private_key = 'YOUR_PRIVATE_KEY'
client = Client(public_key, private_key)

# A single connection can listen to a maximum of 1024 streams.
# WebSocket connections have a limit of 5 incoming messages per second
bm = BinanceSocketManager(client)

# Returns quantity of asset, necessary for creating an order
def getQuantity(sym): 
    # Remove USDT & BTC
    if (sym[-4:] == "USDT"):
        sym = sym[:-4]

    # Not if, otherwise BTCUSDT wil be nothing
    elif (sym[-3:] == "BTC"):
        sym = sym[:-3]

    assets = (client.get_account()).get('balances')
    for asset in assets:
        if asset['asset'] == sym:
            # Times 0.999 sometimes it will run into issues if everything is used
            return (float(asset.get('free')) + float(asset.get('locked'))) * 0.999
   
# === Changes stop_loss_orders ===
def trailingStopLoss(sym, close):

    # Get all the trades made with this symbol
    trades = pd.DataFrame(client.get_my_trades(symbol = sym))

    # Filter on buy orders
    buy_orders = trades[trades['isBuyer']==True]

    # Take the latest BuyOrder
    latest_buy = buy_orders.iloc[-1]

    # Take the price
    original_price = float(latest_buy['price'])

    # Take the ID
    original_id = latest_buy['orderId']
    
    # Gets the orderId of open orders, also gets the last stop price
    # Will only return 1 element, if you have 1 stop loss opened
    openOrder = client.get_open_orders(symbol= sym)

    #If there is no open order, do nothing (could be replaced by making a stop-loss)
    if not openOrder:
        # Code for making a stop-loss
        # Use info in buy_orders
        return  

    # If the openOrder is not a stop loss
    if openOrder[0]['type'] != 'STOP_LOSS_LIMIT':
        return

    # If the current close price is greater than the original price, change the stop loss
    if close > original_price:    

        # Get the info of the old order, which needs to be cancelled
        # Oldest order will be the latest openOrder
        current_stop = float(openOrder[0]['stopPrice'])
        current_stop_id = openOrder[0]['orderId']

        # Calculate the original stop price percentage
        allOrders = pd.DataFrame(client.get_all_orders(symbol = sym))
        
        # Filter on STOP_LOSS_LIMIT & Sell side
        allOrders = allOrders[(allOrders['type'] == 'STOP_LOSS_LIMIT') & (allOrders['side']=='SELL')]

        # Find the stop_loss order closest to the buy order
        original_stop = allOrders[allOrders['orderId'] > original_id]

        # Get the stop price of that latest stop_loss order
        original_stop_price = float(original_stop.iloc[0]['stopPrice'])

        # Calculate the old stop percentage
        # Will be 1 + (95 - 100) / 100 = 0.95
        stop_percentage = 1 + (original_stop_price - original_price) / original_price

        # Necessary for determining if we cancel the order or not
        # New_stop needs to have a precision that is allowed
        tick_size = float(client.get_symbol_info(sym)["filters"][0].get("tickSize"))
        tick_precision = int(round(-math.log (tick_size, 10), 0))

        # Set a stop loss at stopPercentage below the current price 
        # Round it, otherwise it might not be allowed to use
        new_stop = round(close * stop_percentage, tick_precision) 

        # If new stop price is higher than the old one, cancel old stop loss
        if new_stop > current_stop:
            # Cancel old stop loss order, needs that order id
            # For some reason this sometimes doesn't work and gives error:
            # binance.exceptions.BinanceAPIException: APIError(code=-2011): Unknown order sent.
            try:
                client.cancel_order(symbol = sym, orderId = current_stop_id) 
            except Exception as e:
                print(e)

        # If new stop would be lower than the old one, exit function here
        else:
            return 

        # If no stop-loss exists or new stop is higer than old one, make new stop loss order
        # Limit price is the stop price but 1% smaller
        limit_price = round(new_stop * 0.99, tick_precision) 

        # The same method used for tick_size
        step_size = float(client.get_symbol_info(sym)["filters"][2].get("stepSize"))
        step_precision = int(round(-math.log(step_size, 10), 0))
        quant = round(getQuantity(sym), step_precision)

        # Try placing the new stop_loss order
        try:
            client.create_order(symbol = sym, side = "SELL", type = "STOP_LOSS_LIMIT", quantity = quant, stopPrice = new_stop, price = limit_price, timeInForce = "GTC")
            msg = " ".join(["STOP_LOSS_LIMIT", sym, "$" + str(close), str(new_stop), str(limit_price), "stop %", str(stop_percentage)])
            print(msg)

        # Common non-fatal errors:
        # APIError(code=-2011): Unknown order sent.
        # APIError(code=-2010): Account has insufficient balance for requested action.
        except Exception as e: 
            print(e)           
            msg = " ".join(["Error!, Tried:","STOP_LOSS_LIMIT", sym, "$" + str(close), str(new_stop), str(limit_price), "stop %", str(stop_percentage)])
            print(msg)       

# === Websocket interpreter ===
def get1dCandles(info):
    try:
        # We only care about the symbols we own
        owned = [d for d in info if d['s'] in ownedList]

        # Get the important data
        for ticker_data in owned:
            sym = ticker_data['s']
            close = float(ticker_data['c'])

            # Set a trailing stop loss, using this data
            trailingStopLoss(sym, close)

    # Catch any exception
    except Exception as e: 
        # Print out all the error information
        print(e)
        print(traceback.format_exc())
        print(sym)

        #Wait 1 min before retrying
        print("retrying in 60 sec")
        time.sleep(60) 
        print("retrying...")

        #Refresh client
        refresh()

# Sometimes this is necessary when there are errors
def refresh():
    client = Client(public_key, private_key)

# === Getting user data, through start_user_socket ===
def userInfo(info):
    operation = info.get('e')

    # Other operations are balanceUpdate and outboundAccountInfo
    if operation == 'executionReport':
        sym = info.get('s')         # ie 'YFIUSDT'

        side =  info.get('S')       # ie BUY
        orderType =  info.get('o')  # ie LIMIT, not used currently

        execType =  info.get('x')   # Only importent if it's 'TRADE'

        if execType == "TRADE":             # If a new asset is Bought
            if side == "BUY":               # If it's a sell adding is not necessary
                if sym not in ownedList:    # Don't want it twice in list
                    ownedList.append(sym)           
                    print("Bought " + sym)

            if side == "SELL":              # So the trailing stop does not get updated
                if sym in ownedList:        # First check if it is in ownedList, otherwise this is unnecessary

                    print("Sold " + sym)

                    # Default pairing is USDT
                    BTC = False

                    # If the last 3 characters are BTC it is a BTC pair
                    if (sym[-3:] == "BTC"):
                        BTC = True

                    # Get the amount that is owned
                    total = getQuantity(sym)

                    # If it is a BTC pair, use BTC price to calculate value in dollar
                    if (BTC == True):
                        usdt_val = total * float((client.get_avg_price(symbol = sym).get('price'))) * float((client.get_avg_price(symbol = 'BTCUSDT').get('price')))

                    # It is a USDT pair
                    if (BTC == False):
                        usdt_val = total * float((client.get_avg_price(symbol = sym).get('price')))

                    # If the asset value in usdt is less than 10, then remove it
                    if usdt_val < 10:
                        ownedList.remove(sym)
                        print("Removed from ownedList: " + sym)

# ownedList keeps track of all the assets that are currently in possession
ownedList = []

# Only used at start, since userInfo() cant get old info
def getOwned():

    # Returns list of dictionary of all the orders that are open
    open_order = client.get_open_orders()
   
    # Convert it to a pandas dataframe
    # COULD USE LIST COMPREHENSION INSTEAD!
    orders_df = pd.DataFrame(open_order)

    # Filter on 'type': 'STOP_LOSS_LIMIT', take only the symbols, convert it to list
    try:
        owned = orders_df[orders_df['type']=='STOP_LOSS_LIMIT']['symbol'].tolist()
    # In case there are no active stop_loss_limit orders
    except Exception as e: 
        return

    # ownedList consists of the pairs, for instance 'BTCUSDT'
    for asset in owned:
        try:
            # Add the asset to ownedList
            ownedList.append(asset)
            print(asset, end =" ") 

        except Exception as e: 
                    # Print out all the error information
                    print(e)
                    print(traceback.format_exc())
                    print("Crashed in getOwned() at symbol:")
                    print(asset)
    print()
  
# === Start the sockets ===
def start():
    tijd = datetime.datetime.now().strftime("%H:%M:%S")
    print("Starting at " + tijd)
    
    # Get the currently owned symbols
    getOwned()

    # Start the sockets
    bm.start_user_socket(userInfo)
    bm.start_miniticker_socket(get1dCandles)
    bm.start()

    tijd = datetime.datetime.now().strftime("%H:%M:%S")
    print("Sockets started at " + tijd)

    # Maximum: after 24 hours restart (86400)
    time.sleep(86400)

    tijd = datetime.datetime.now().strftime("%H:%M:%S")
    print("Stopped at " + tijd)

    # Close the program
    os._exit(0) 

# === Start the code ===
# So it can be run using run.py without parameters
if __name__ == '__main__':
    start()