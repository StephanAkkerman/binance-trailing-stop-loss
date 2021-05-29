import os
    
if __name__ == '__main__':
    while True:
        try:
            os.system("python3 BinanceAlertV3.py")
        except Exception as e:
            print("Caught exception in run.py")
            print(e)
            
