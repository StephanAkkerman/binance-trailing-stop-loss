#!/usr/bin/python3
from binance.client import Client
from binance.websockets import BinanceSocketManager
from binance.enums import *
import binance
import datetime     # Used for converting time to string
import math         # Used for calculating the precision for making orders
import time         # Used for time.sleep
import traceback    # Used for debugging
import os           # Used for exiting the code, necessary for RaspberryPi restart
import pandas as pd # Used for handling dictionaries and lists
import numpy as np

# Max 1200 requests per minute; 10 orders per second; 100,000 orders per 24hrs
public_key = 'public key'
private_key = 'private key'

client = Client(public_key, private_key)

# Removes the last part of pair: BTCUSDT -> BTC
def removePairing(sym):
    # Pairs found at: https://www.binance.com/en/markets

    # The pairing with a length of 4
    if (sym[-4:] == "USDT"):
        return(sym[:-4])

    elif (sym[-4:] == "BUSD"):
        return(sym[:-4])
    
    elif (sym[-4:] == "TUSD"):
        return(sym[:-4])

    elif (sym[-4:] == "USDC"):
        return(sym[:-4])

    elif (sym[-4:] == "BIDR"):
        return(sym[:-4])

    elif (sym[-4:] == "IDRT"):
        return(sym[:-4])

    elif (sym[-4:] == "BVND"):
        return(sym[:-4])

    # Otherwise the pair has a length of 3
    else:
        return(sym[:-3])

# Returns quantity of asset, necessary for creating an order
def getQuantity(sym): 

    sym = removePairing(sym)

    assets = (client.get_account()).get('balances')
    for asset in assets:
        if asset['asset'] == sym:
            # Return total quantity that can be used
            # Times 0.999, otherwise there are a lot API error 2010
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
                print("Cancelled old stop loss")
            except Exception as e:
                print(e)
                print("Error cancelling old order")
                # If order cant be cancelled, return
                return

        # If new stop would be lower than the old one, exit function here
        else:
            return 

        # If no stop-loss exists or new stop is higer than old one, make new stop loss order
        # Limit price is the stop price but 1% smaller
        limit_price = round(new_stop * 0.99, tick_precision) 

        # The same method used for tick_size
        step_size = float(client.get_symbol_info(sym)["filters"][2].get("stepSize"))
        step_precision = int(round(-math.log(step_size, 10), 0))

        # Convert to string, keeping it as a float will result in errors
        limit_price = f"{np.format_float_positional(limit_price)}"
        new_stop = f"{np.format_float_positional(new_stop)}"

        # Remove "." in case of converting number like 1.0, which will result in 1.
        if (limit_price[-1] == '.'):
            limit_price = limit_price[:-1]

        if (new_stop[-1] == '.'):
            new_stop = new_stop[:-1]

        # Try placing a stop loss order
        for x in range (0,10): # Max 10 times
            try:
                quant = round((getQuantity(sym) * (0.995 ** x)), step_precision)
                client.create_order(symbol = sym, side = "SELL", type = "STOP_LOSS_LIMIT", quantity = quant, stopPrice = new_stop, price = limit_price, timeInForce = "GTC")
                
                msg = " ".join(["STOP_LOSS_LIMIT", sym, "$" + str(close), str(new_stop), str(limit_price), "stop %", str(stop_percentage)])
                print(msg)
                break

            except binance.exceptions.BinanceAPIException as e:
                # Try again with lower quantity
                if (e.message == "Account has insufficient balance for requested action."):
                    print("Retrying with lower quantity, x = " + str(x))
                    pass

                # Maybe undo the latest cancelled order after it fails for 10th time
                else:
                    msg = " ".join(["Error at create_order, Tried:","STOP_LOSS_LIMIT", sym, "close=" + str(close), "quantity=", str(quant), "stopPrice=", str(new_stop), "price=", str(limit_price), "stop %", str(stop_percentage)])
                    print(msg)  
                    print(e.message)       

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

        execType =  info.get('x')   # Can be TRADE, NEW or CANCELLED

        # If something is bought add it to ownedList
        if execType == "TRADE":             # If a trade is made succesfully
            if side == "BUY":               # If it's a sell adding is not necessary
                if sym not in ownedList:    # Don't want it twice in list
                    ownedList.append(sym)    
                    
                    print("Bought " + sym)
                    print("Owning =", end =" ") 
                    print(ownedList)

        # Remove from ownedList if it is sold
            if side == "SELL": 
                if sym in ownedList:        
                    ownedList.remove(sym)

                    print("Sold " + sym)
                    print("Owning =", end =" ") 
                    print(ownedList)

        # If a new stop loss has been made
        if execType == "NEW":
            if side == "SELL":              
                # Add to owned list if new stop loss order has been made
                if orderType == 'STOP_LOSS_LIMIT':
                    if sym not in ownedList:
                        ownedList.append(sym)

                        print("Added: " + sym)
                        print("Owning =", end =" ") 
                        print(ownedList)

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
            
        except Exception as e: 
                    # Print out all the error information
                    print(e)
                    print(traceback.format_exc())
                    print("Crashed in getOwned() at symbol:")
                    print(asset)
    
    # Print everything in ownedList
    print("Owning =", end =" ") 
    print(ownedList)
  
# === Start the sockets ===
def start():
    tijd = datetime.datetime.now().strftime("%H:%M:%S")
    print("Starting at " + tijd)
    
    # Get the currently owned symbols
    getOwned()

    # Start the sockets
    bm = BinanceSocketManager(client)
    bm.start_user_socket(userInfo)
    bm.start_miniticker_socket(get1dCandles)
    bm.start()

    # Print the starting time
    tijd = datetime.datetime.now().strftime("%H:%M:%S")
    print("Sockets started at " + tijd)

    # Maximum: after 24 hours restart (86400)
    time.sleep(86400)

    # Close all sockets
    bm.close()

    # Print the stopping time
    tijd = datetime.datetime.now().strftime("%H:%M:%S")
    print("Stopped at " + tijd)

    # Start again
    start()

# === Start the code ===
# So it can be run using run.py without parameters
if __name__ == '__main__':
    start()