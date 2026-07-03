#!/usr/bin/env bash

IFACE="${1:-wlp0s20f3}"

my_ips=$(hostname -I)

name_of_ip() {
  ip="$1"

  if echo "$my_ips" | grep -qw "$ip"; then
    echo "ME"
    return
  fi

  name=$(getent hosts "$ip" | awk '{print $2}' | head -n1)

  if [ -n "$name" ]; then
    echo "$name"
  else
    echo "$ip"
  fi
}

printf "%-26s | %-3s | %-35s | %-6s | %-10s | %s\n" \
  "TIME" "L3" "FLOW" "L4" "TYPE" "INFO"

printf -- "%.0s-" {1..105}
echo

sudo tcpdump -i "$IFACE" -nn -tttt -l icmp 2>/dev/null | while read -r line; do
  time=$(echo "$line" | awk '{print $1" "$2}')
  src=$(echo "$line" | awk '{print $4}')
  dst=$(echo "$line" | awk '{print $6}' | sed 's/://')

  src_name=$(name_of_ip "$src")
  dst_name=$(name_of_ip "$dst")

  if echo "$line" | grep -q "echo request"; then
    type="Ping"
    info="echo request"
  elif echo "$line" | grep -q "echo reply"; then
    type="Ping"
    info="echo reply"
  else
    type="ICMP"
    info=$(echo "$line" | cut -d: -f2- | sed 's/^ //')
  fi

  flow="${src_name} > ${dst_name}"

  printf "%-26s | %-3s | %-35s | %-6s | %-10s | %s\n" \
    "$time" "IP" "$flow" "ICMP" "$type" "$info"
done
