#!/usr/bin/python3 -u
import json
import os
import sys

if sys.stdin.readline():
    print(json.dumps({'id': 1, 'result': {'protocol': 1, 'os': 'linux',
          'pid': os.getpid(), 'image': os.path.realpath(sys.argv[0])}}), flush=True)
if sys.stdin.readline():
    print(json.dumps({'id': 999, 'result': None}), flush=True)
for line in sys.stdin:
    pass
