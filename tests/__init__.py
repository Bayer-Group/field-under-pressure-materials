# -*- coding: utf-8 -*-
import sys
import os

# Dodaj katalog główny projektu do sys.path, aby importy działały bezproblemowo
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
