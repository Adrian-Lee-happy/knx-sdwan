#!/bin/sh
knx_public_ipv4() {
 printf '%s\n' "$1" | awk -F. '
 NF!=4 {exit 1}
 {
  for(i=1;i<=4;i++) if($i!~/^[0-9]+$/ || $i>255 || (length($i)>1 && substr($i,1,1)=="0")) exit 1;
  a=$1+0; b=$2+0; c=$3+0;
  if(a==0 || a==10 || a==127 || a>=224) exit 1;
  if(a==100 && b>=64 && b<=127) exit 1;
  if(a==169 && b==254) exit 1;
  if(a==172 && b>=16 && b<=31) exit 1;
  if(a==192 && b==168) exit 1;
  if(a==192 && b==0 && (c==0 || c==2)) exit 1;
  if(a==192 && b==88 && c==99) exit 1;
  if(a==198 && (b==18 || b==19)) exit 1;
  if(a==198 && b==51 && c==100) exit 1;
  if(a==203 && b==0 && c==113) exit 1;
 }'
}
