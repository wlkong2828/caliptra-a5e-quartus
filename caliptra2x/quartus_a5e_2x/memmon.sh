#!/bin/bash
# Sample box memory + container RSS every 20 s until the q2x_syn container exits.
export PATH=/workspace/docker-bin:$PATH
out=${1:-memmon.log}; sleep 30
while docker ps --format '{{.Names}}' | grep -q '^q2x_syn$'; do
  echo "$(date +%H:%M:%S) $(free -m | awk '/Mem:/{print "used="$3" avail="$7}') $(docker stats --no-stream --format '{{.MemUsage}}' q2x_syn)" >> $out
  sleep 20
done
echo "$(date +%H:%M:%S) container gone" >> $out
