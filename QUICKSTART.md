# Quick Start: install vdl2-observatory

This guide takes you from a fresh computer to a working VDL2 receiver, step by step.
You only need to be able to open a terminal window and type (or paste) commands.

VDL2 (VHF Data Link Mode 2) is how airliners exchange text messages with the ground on
frequencies around 136.9 MHz. A receiver near an airport or under a busy airway hears hundreds
of aircraft a day.

The installer does all the hard work: it downloads what it needs, builds the program,
and sets it up to start by itself every time the computer starts.

## Before you start

You need:

- **A computer** running Ubuntu or Debian (or a system based on them), connected to the
  internet. It's been tested most on Ubuntu 22.04. It doesn't need much power: the receiver
  uses about a seventh of one processor core on a small PC.
- **An RTL-SDR dongle** plugged into a USB port, such as an RTL-SDR Blog V3. (The Blog V4 needs its maker's own
  driver, which the installer doesn't set up.)
- **A VHF airband antenna** connected to the dongle, outdoors or as high as you can get it.
  An antenna for 118-137 MHz is ideal; a 1090 MHz ADS-B antenna will hear very little.
- **Your password** for this computer. The installer will ask for it.
- **About 15 minutes.** Most of that is the computer working while you wait.

The dongle can only be used by one program at a time. If dumpvdl2, acarsdec, rtl_tcp or
another program is already using it, stop that program first (or use a second dongle).

Two tips for the terminal:

- **Pasting:** copy a command from this page, then press **Ctrl+Shift+V** in the terminal
  (plain Ctrl+V doesn't work there). Press **Enter** to run it.
- **Passwords don't show.** When asked for your password, type it and press Enter.
  Nothing appears on screen as you type; that's normal.

## Step 1: Open a terminal

On Ubuntu, press **Ctrl+Alt+T**. On other systems, find **Terminal** in the applications menu.

A window opens with a line ending in `$`. That's where you type commands.

## Step 2: Install git

`git` is the tool that downloads vdl2-observatory. Copy this line, paste it into the
terminal, and press Enter:

```
sudo apt update && sudo apt install -y git
```

Type your password when asked. Wait until the `$` prompt comes back.

## Step 3: Download vdl2-observatory

```
git clone https://github.com/mebrown47/vdl2-observatory.git
```

This creates a folder called `vdl2-observatory` in your home folder.

## Step 4: Go into the folder

```
cd vdl2-observatory
```

## Step 5: Run the installer

Make sure the dongle is plugged in, then:

```
./install.sh
```

Type your password if asked. The installer works through several stages and prints a
line for each one. **Building takes a few minutes**; let it run.

## Step 6: Answer the questions

Partway through, the installer asks a few questions. Each one shows a suggested answer in
`[brackets]`; **press Enter to accept it.** If you're not sure, the suggested answer is fine.

| The installer asks | What it means | If unsure |
|---|---|---|
| **Which one** | Which dongle to use, from a numbered list (only asked if you have more than one) | Press Enter for the first one |
| **Channel plan, us or eu** | Which set of VDL2 frequencies to listen to | `us` in North America, `eu` in Europe |
| **Tuner gain in dB, or auto** | How much the dongle amplifies the signal | Press Enter (auto) |
| **Frequency correction in ppm** | How far off frequency your dongle is | Press Enter (0) for now; see Step 9 |
| **Power an LNA through the dongle's bias tee** | Whether the dongle sends power up the antenna cable to an amplifier | Type `y` only if your antenna has an amplifier that needs power from the cable |
| **Feed frames over UDP** | Share the messages you receive with other sites or programs, such as a local acarshub or an aggregator. Give each one as `HOST:PORT`, with spaces between | Press Enter (none), or the addresses the site gave you |
| **Station ID for your feeds** | A name for your station on those sites, such as `XYZ-VDL2` (only asked if you feed) | Your choice, or Enter for none |
| **Aircraft positions as SBS/BaseStation** | Send aircraft positions to a map program such as tar1090 or Virtual Radar Server | Press Enter (none) |

You can change any answer later (see "Change your answers" below).

## Step 7: Open your receiver's pages

When the installer finishes, its last lines show two web addresses, like this:

```
  Live page:    http://192.168.1.50:8889/
  Observatory:  http://192.168.1.50:8891/
```

Open them in a web browser, on this computer or any other one on your home network.
On this computer you can also use `http://localhost:8889` and `http://localhost:8891`.

- **Live page (8889):** what the receiver is hearing right now: aircraft and ground stations
  on a map, the newest messages, and a **Receiver** panel showing the dongle's health.
- **Observatory (8891):** charts of what you've received over time, the ground stations
  you hear, and every aircraft's messages.

The two pages link to each other.

## Step 8: Give it some time

- Messages arrive whenever an aircraft in range talks. Near an airport or under an airway
  the live page fills within minutes; in a quiet area it can take longer, and nights are quieter.
- The Observatory's charts fill in over the first hour.
- Ground stations appear on the maps as aircraft report where they are.

That's it. The receiver keeps running, and starts again by itself after a reboot.

## Step 9: Set the frequency correction (optional)

Most dongles are slightly off frequency, which costs weak messages. After an hour or two,
look at the **Receiver** panel on the live page. Once it has heard enough aircraft it shows
a suggested `--ppm` value. If it differs from what you have, run
`./install.sh --reconfigure` and enter it at the **Frequency correction** question.

A dongle with a TCXO (such as the RTL-SDR Blog V3) usually needs none.

## Later on

Open a terminal and go into the folder first (`cd vdl2-observatory`), then:

| To | Type |
|---|---|
| **Update to the latest version** | `./install.sh --update` |
| **Change your answers** (gain, ppm, feeds) | `./install.sh --reconfigure` |
| **Remove it** (your settings and data are kept) | `./install.sh --uninstall` |

## If something goes wrong

**"Permission denied" when running `./install.sh`:** type `bash install.sh` instead.

**The installer says "no RTL-SDR on USB":** check the dongle is plugged in, unplug it and
plug it back in, then run `sudo systemctl start vdl2-sniffer`.

**The live page shows no messages after an hour:** check the antenna is connected and
outdoors, and that the channel plan matches where you are (`us` or `eu`). Make sure no other
program is using the dongle.

**The pages won't open from another computer** but work on this one: the computer's
firewall is blocking them. Run:

```
sudo ufw allow 8889/tcp && sudo ufw allow 8891/tcp
```

**Anything else:** make a diagnostics report and send it to whoever is helping you:

```
cd vdl2-observatory
./diagnose.sh
```

It takes about 10 seconds and changes nothing. It writes a file named like
`diagnose-yourcomputer-20261111-120000.txt` in the folder and prints its name. The report
includes your settings and the ground stations you hear, which tell roughly where you are,
so share it privately rather than posting it in public.

---

For what vdl2-observatory does and every option, see the [README](README.md).
