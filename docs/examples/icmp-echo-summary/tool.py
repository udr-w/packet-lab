"""Summarise ping echo statistics. Generated tool: untrusted; runs under the restricted runner."""
import json
import re
import sys


def summarise(ping_output):
    m = re.search(r"(\d+) packets transmitted, (\d+) received", ping_output)
    transmitted = int(m.group(1)) if m else 0
    received = int(m.group(2)) if m else 0
    loss = 0.0 if transmitted == 0 else round(100 * (transmitted - received) / transmitted, 1)
    return {"transmitted": transmitted, "received": received, "loss_percent": loss}


def main():
    data = json.load(sys.stdin)
    print(json.dumps(summarise(data["ping_output"])))


if __name__ == "__main__":
    main()
