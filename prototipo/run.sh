#!/bin/bash

if [ "$USER" == "root" ]; then
	cd /home/sdn
	source venv/bin/activate
	cd prototipo
	mkdir -p relatorios
	killall iperf3 2> /dev/null
	python3 main.py
	rm -f controller_routing_mode.tmp graph_topo.pickle
	chown -R sdn:sdn relatorios
else
	sudo bash $0
fi

