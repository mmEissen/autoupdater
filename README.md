#  Auto-Updater

A small bootstrap project to install, run, and automatically update a python project on a RaspberyPI. I mainly built this for my [Fetap Project](https://github.com/mmEissen/fetap).

## Use Case

This project is useful if:
- You want to run a project on a raspberry PI
- Your project is written in python and the dependencies can be defined in a `requirements.txt`
- You will have limited access to the device while it is in operation
- Your device has a (reasonably) stable and continuous internet connection

## Usage

### Basic Usage

Install Auto-Updater via pip:
```
pip install auto-updater
```

Host a `requirements.txt` file somewhere on the web with a static url (the easiest would be get the raw file url from github). Then run the auto-updater with:

```
python -m auto-updater <url to requirements.txt> <your-module> [your-args]*
```

Auto Updater will now:
- create a venv
- install all requirements in it
- run `python -m <your-module> [your-args]*` in the venv

While your program is running it will:
- continuously check for changes to the requirements.txt
- if changes are detected send a `SIGTERM` to your program and wait for it to terminate
- if the program does not terminate after a (configurable) timeout send a `SIGKILL`
- once terminated, update the requirements in the venv and restart the program

If at any point your program terminates it will be restarted.

## Recommendations

You should configure the Auto-Updater as a service to ensure it gets started on a reboot of your device. To do this create a file `/lib/systemd/system/<your-service-name>.service` on your device and add:
```
[Unit]
Description=<Description>
After=network-online.target

[Service]
ExecStart=/usr/bin/stdbuf -oL <full-path-to-python>/python -m autoupdater <url to requirements.txt> <your-module> [your-args]*
WorkingDirectory=<directory-to-create-venv-in>
StandardOutput=inherit
StandardError=inherit
Restart=always
User=<user-to-run-as>

[Install]
WantedBy=multi-user.target
```
Make sure to fill in the appropriate values for your project.

*Note: The `/usr/bin/stdbuf -oL` ensures that all output shows up in the logs correctly.*

Now run:
```
sudo systemctl enable <your-service-name>.service
sudo systemctl start <your-service-name>
```
