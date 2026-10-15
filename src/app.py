import os
import sys
import json
import requests
from PyQt6.QtWidgets import QApplication
from FeimUI import MainWindow

MotherPath = os.path.dirname(
    os.path.dirname(
        os.path.abspath(__file__)
    )
)
with open(os.path.join(MotherPath,"config","config.json"),"r",encoding="utf-8") as f:
    MainConfig = json.load(f)
app = QApplication(sys.argv)

def main():
    try:
        mw = MainWindow(MainConfig, os.path.join(MotherPath, "config", "config.json"))
        mw.show()
        sys.exit(app.exec())
    except Exception as e:
        print(f"[Error] {e}")

if __name__ == "__main__":
    main()