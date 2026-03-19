# Local Prison Architect Multi-Player Server
An all-in-one packaged project to setup your own local Prison Architect server!

## Quick Setup
_This only works if you are on [LAN](https://en.wikipedia.org/wiki/Local_area_network), see [below](#playing-with-friends-wan) if unsure_
1) Redirect `ns.exitgames.com` to localhost in your hosts file.
   1) [Youtube tutorial](https://youtu.be/AC6hs_1_yOI?si=GQp_XX3_W0V7orjV) (not mine)
   2) Add the line `127.0.0.1 ns.exitgames.com` to your hosts file.
2) Install the required dependencies.
   1) `pip install -r requirements.txt`
3) Run the local server
   1) `python main.py local`

### Playing with Friends ([WAN](https://en.wikipedia.org/wiki/Wide_area_network))
_If your friends are on a different network than you, such as at their house and you are at yours_
1) Find your [public IP address](https://www.geeksforgeeks.org/computer-networks/what-is-public-ip-address/)
   1) In PowerShell:
      ```powershell
         (Invoke-RestMethod https://ipinfo.io).ip
      ```
   2) Or, search for [What is My IP Address](https://whatismyipaddress.com/)
2) Add a port forwarding rule.
   1) Add a rule for ports 4530-4533 (the range) to your firewall.
      1) Run this as Admin
         ```powershell
         netsh advfirewall firewall add rule name="Photon Server" dir=in action=allow protocol=TCP localport=4530-4533
         ```
   2) Add a [port forwarding](https://en.wikipedia.org/wiki/Port_forwarding) rule on your router.
      1) [Tutorial](https://www.noip.com/support/knowledgebase/general-port-forwarding-guide)
3) Tell your friends to add a redirection from `ns.exitgames.com` to your IP address in their hosts file.
   1) For example, if your IP address is `1.2.3.4`, they should add this line to their file:
         `1.2.3.4 ns.exitgames.com`
4) Run the local server
   1) `python main.py local -l 0.0.0.0 -i [YOUR_IP_ADDRESS]`
   2) Replace `[YOUR_IP_ADDRESS]` with your public IP address.
5) _(optional)_ If your connection isn't strong, try adding `--timeout 30` to the command.


## Legal Notice

This project is an independent interoperability research project.

No proprietary source code from Prison Architect or the Photon SDK is included in this repository.

All implementations were written from scratch based solely on behavioral analysis of the network protocol.

This project is intended for educational and research purposes only.

This project does not bypass DRM, licensing systems, or authentication mechanisms.

---

Checkout the [journal](./journal/journal.md) to see how to do this yourself!
