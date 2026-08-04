#!/bin/bash

if [ "$USER" == "root" ]; then
	cd /home/mininet/path-aware-datasets
	source venv/bin/activate
	cd prototipo
	mkdir -p relatorios
	killall iperf3 2> /dev/null
	python3 main.py
	rm -f controller_routing_mode.tmp graph_topo.pickle
	chown -R mininet:mininet relatorios
else
	sudo bash $0
fi

