# install WiFi ap 5GHz
# https://www.raspberrypi.org/documentation/configuration/wireless/access-point-routed.md
# ./install_ap wlan0 1 LacmusAP - setup AP on iface wlan0 with IP 192.168.4.1 and ssid=passwd=LacmusAP

sudo apt install -y hostapd dnsmasq

sudo systemctl unmask hostapd
sudo systemctl enable hostapd


sudo echo "interface $1 
    static ip_address=192.168.4.$2/24
    nohook wpa_supplicant" >> /etc/dhcpcd.conf


sudo mv /etc/dnsmasq.conf /etc/dnsmasq.conf.orig
sudo echo "interface=$1 # Listening interface
dhcp-range=192.168.4.4,192.168.4.20,255.255.255.0,24h
                # Pool of IP addresses served via DHCP
domain=wlan     # Local wireless DNS domain
address=/pi.wlan/192.168.4.$2
                # Alias for this router" > /etc/dnsmasq.conf

sudo rfkill unblock wlan

sudo echo "country_code=US
interface=$1
hw_mode=a
channel=48
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
wpa=2
wpa_key_mgmt=WPA-PSK
wpa_pairwise=TKIP
rsn_pairwise=CCMP
ssid=$3
wpa_passphrase=$3
" >> /etc/hostapd/hostapd.conf