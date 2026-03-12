# Run webapp on EC2 (systemd, survive SSH exit)

So the app keeps running after you disconnect and restarts on reboot.

## SSH into the instance

From the project root (where `aws_ec2.pem` lives):

```bash
ssh -i aws_ec2.pem ubuntu@ec2-98-89-0-90.compute-1.amazonaws.com
```

If your instance’s public DNS or IP changes, update the host in the command above.

## 1. Create the systemd unit

On the EC2 instance:

```bash
sudo nano /etc/systemd/system/tsa-webapp.service
```

Paste (adjust paths if your repo is elsewhere):

```ini
[Unit]
Description=TSA Wait Times webapp
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/tsa
Environment=FLASK_HOST=0.0.0.0
Environment=FLASK_DEBUG=false
ExecStart=/home/ubuntu/tsa/venv/bin/python app.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Save and exit.

## 2. Enable and start

```bash
sudo systemctl daemon-reload
sudo systemctl enable tsa-webapp
sudo systemctl start tsa-webapp
sudo systemctl status tsa-webapp
```

If status shows `active (running)`, open **http://\<ec2-public-ip\>:5000** in your browser (and ensure the EC2 security group allows inbound port 5000).

## 3. Useful commands

- **Logs:** `journalctl -u tsa-webapp -f`
- **Restart:** `sudo systemctl restart tsa-webapp`
- **Stop:** `sudo systemctl stop tsa-webapp`
