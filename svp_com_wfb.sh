# air
## bench
sudo wfb_tx -K /etc/drone.key -p 1 -u 7555 wlan0
sudo wfb_rx -K /etc/drone.key -p 2 -u 7558 wlan0
## ft
sudo wfb_tx -K /etc/drone.key -p 1 -u 6555 wlan0
sudo wfb_rx -K /etc/drone.key -p 2 -u 6558 wlan0



# ground
## bench
sudo wfb_rx -K /etc/gs.key -p 1 -u 7556 wlan0
sudo wfb_tx -K /etc/gs.key -p 2 -u 7557 wlan0
## ft
sudo wfb_rx -K /etc/gs.key -p 1 -u 6556 wlan0
sudo wfb_tx -K /etc/gs.key -p 2 -u 6557 wlan0