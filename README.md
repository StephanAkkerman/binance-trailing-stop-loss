# How to set up
Add your public and private API keys on line 13 and 14./

# How it works
There is no user interaction necessary. If you place a stop loss order after buying a coin on Binance, the program will calculate the procentual difference between the buying price and the first stop loss.
This first stop loss is then used as a reference for further stop loss percentages.

# Windows & MacOS
These OSes do not have the problem that Linux based system have. If you run TrailingStop.py alone, it should work.

# Linux
There is a problem where the sockets can be closed or restarted once they have started running.
Unfortunately, the developer of python-binance has not fixed this problem yet.
So to fix this problem, you need to run run.py which will restart the trailing stop loss program every 24 hours.

# Examples
> Market buy 1000 DOGE/USDT at 0,295$.
> Place a stop loss at 0,26$.
> Procentual difference is calculated: 13,46%.
> If the price rises, the difference between current close price and stop price will stay 13,46%.
> If the price drops, stop loss price will stay where it is.
