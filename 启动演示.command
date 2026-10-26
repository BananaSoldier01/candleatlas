#!/bin/zsh
cd -- "${0:A:h}"
python3 server.py --demo --port 8765
read '?演示已停止。按回车关闭窗口…'
