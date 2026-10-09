# Local Prison Architect Multi-Player Server
An all-in-one packaged project to setup your own local Prison Architect server!

## Quick Setup
_This only works if you are on [LAN](https://en.wikipedia.org/wiki/Local_area_network), see [below](#playing-with-friends-wan) if unsure_
1) Redirect `ns.exitgames.com` to localhost in your hosts file.
   1) [Youtube tutorial](https://youtu.be/AC6hs_1_yOI?si=GQp_XX3_W0V7orjV) (not mine)
   2) Add the line `127.0.0.1 ns.exitgames.com` to your hosts file.
2) Install the required dependencies.
   1) `pip install -r requirements.txt`
   2) Requires Python 3.10 or newer.
3) Run the local server
   1) `python main.py local`
   2) Or just `python main.py` for an interactive setup wizard.
   3) `python main.py --help` (or `python main.py local --help`) lists all options.

### Quick Setup with Docker
_No Python needed, just [Docker](https://docs.docker.com/get-docker/)_
1) Redirect `ns.exitgames.com` in your hosts file, same as step 1 above.
2) Run the prebuilt image:
   ```bash
   docker run -d --name prison-architect-server --restart unless-stopped \
      -p 4530-4533:4530-4533 \
      -e PUBLIC_IP=127.0.0.1 \
      ghcr.io/michael-k-stein/prison-architect-server:latest
   ```
   1) For friends over WAN, set `PUBLIC_IP` to your public IP and follow the
      firewall/port forwarding steps [below](#playing-with-friends-wan).
   2) Optional variables: `TIMEOUT` (default `60`), `REGION` (default `local`),
      `MAX_PLAYERS` (default `4`).
3) Check the logs with `docker logs -f prison-architect-server`, stop with
   `docker stop prison-architect-server`.
4) To update: `docker pull ghcr.io/michael-k-stein/prison-architect-server:latest`,
   then `docker rm -f prison-architect-server` and run step 2 again.

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

### Other Photon games keep working
The hosts-file redirect sends *every* Photon-engine game on your machine to this server. That's fine: the server reads each client's app id from its first packet (it's plaintext) and only serves Prison Architect locally. Any other game's traffic is transparently proxied byte-for-byte to the real Photon cloud, so those games keep working as if the redirect wasn't there.

By default the current IP of `ns.exitgames.com` is resolved automatically. To override it:
```powershell
python main.py local --upstream 1.2.3.4:4533
```

## Docker & CI/CD
This repository includes a Docker image workflow for GitHub Container Registry (GHCR).

### Build locally
```bash
docker build -t prison-architect-server:local .
docker run --rm -p 4530-4533:4530-4533 \
   -e PUBLIC_IP=127.0.0.1 \
   prison-architect-server:local
```

### GitHub Actions workflow
The workflow is in `.github/workflows/docker-image.yml`.

- On push to `master`: builds and pushes `ghcr.io/<owner>/<repo>:latest` and a SHA tag.
- On tag `v*`: builds and pushes version tags.
- On pull request: build-only validation (no push).

## Pterodactyl Egg
An importable egg is provided at `deploy/pterodactyl/egg-prison-architect-server.json`.
It uses the prebuilt image `ghcr.io/michael-k-stein/prison-architect-server:latest`;
there is nothing to install.

### Quick setup
1) **Admin -> Nests -> Import Egg**, upload the egg JSON.
2) **Admin -> Nodes -> (node) -> Allocation**: add ports `4530`, `4531`, `4532`, `4533`
   on the node's public IP.
3) **Admin -> Servers -> Create**: pick the egg, use `4530` as the primary allocation
   and add `4531-4533` as additional allocations.
4) Set `PUBLIC_IP` to the node's public IP, then start the server.

The ports are fixed, so only one server per IP. `TIMEOUT`, `REGION`, and
`MAX_PLAYERS` are optional.

## Legal Notice

This project is an independent interoperability research project.

No proprietary source code from Prison Architect or the Photon SDK is included in this repository.

All implementations were written from scratch based solely on behavioral analysis of the network protocol.

This project is intended for educational and research purposes only.

This project does not bypass DRM, licensing systems, or authentication mechanisms.

---

Checkout the [journal](./journal/journal.md) to see how to do this yourself!
