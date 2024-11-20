# Demonstration for SuperComputing 2024 integrated with Nautilus NRP

The overall ideia here is to instantiate resources at FABRIC testbed, instantiate resources at Nautilus NRP and connect them together using AtlanticWave-SDX.

To be able to run this scripts you will need an account at https://portal.nrp-nautilus.io and then join the "amlight" namespace. Then you get your Kube config and place it at ~/.kube/config-nautilus

Then you just run the script run-test.py. THis script will instantiate a Pod at NRP (selecting the k8s-gen4 node, where Nautilus Support team previously kindly created VLAN 3888 for us), and then run a ping to another pre-configured remote server at 10.1.11.254 (the remote server and L2VPN setup will be done by AtlanticWave-SDX)
