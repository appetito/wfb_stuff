sudo apt-get install -y libboost-all-dev \
	libpcap-dev python3-pyudev libpcap0.8-dev \
	python3-pip python3-setuptools python3-wheel \
	python3-pyudev cmake firmware-ath9k-htc

sudo -H pip3 install pyric

mkdir build
cd build
cmake ..
make

cmake -DCMAKE_INSTALL_PREFIX=/ ..
sudo make install

