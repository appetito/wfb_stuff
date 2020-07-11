# air
## bench
sudo wfb_tx -K /etc/drone.key -p 1 -u 7555 -k 4 -n 12 wlan0
sudo wfb_rx -K /etc/drone.key -p 2 -u 7558 -k 4 -n 12 wlan0
## ft
sudo wfb_tx -K /etc/drone.key -p 1 -u 6555 -k 4 -n 12 wlan0
sudo wfb_rx -K /etc/drone.key -p 2 -u 6558 -k 4 -n 12 wlan0

# -k 8 -n 12 - default Reed-Solomin parameter
# Reed-Solomon parameter "k" -- default 8
# Reed-Solomon parameter "n" -- default 12. This means that FEC block size is 12 packets and up to 4 (12 - 8) can be recovered if lost

# ground
## bench
sudo wfb_rx -K /etc/gs.key -p 1 -u 7556 -k 4 -n 12 wlan0
sudo wfb_tx -K /etc/gs.key -p 2 -u 7557 -k 4 -n 12 wlan0
## ft
sudo wfb_rx -K /etc/gs.key -p 1 -u 6556 -k 4 -n 12 wlan0
sudo wfb_tx -K /etc/gs.key -p 2 -u 6557 -k 4 -n 12 wlan0


