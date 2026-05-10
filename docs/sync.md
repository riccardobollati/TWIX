# Sync Guide

## GitHub Sync (always use `twix2.0` branch)

```bash
# Push local changes to remote
git push origin main:twix2.0

# Pull remote changes into local
git fetch origin
git merge origin/twix2.0
```

---

## GCP Server

**Prerequisites** (add to `~/.zshrc` if not already):
```bash
export PATH=/opt/homebrew/share/google-cloud-sdk/bin:"$PATH"
```

**Authenticate** (once per session if token expired):
```bash
gcloud auth login
```

**SSH into server:**
```bash
gcloud compute ssh doc-structure --zone=us-central1-a --project=doc-structure --tunnel-through-iap
```

**Run a command on server without interactive SSH:**
```bash
gcloud compute ssh doc-structure --zone=us-central1-a --project=doc-structure --tunnel-through-iap --command="<your command>"
```

**Pull latest code on server** (after pushing to `twix2.0`):
```bash
gcloud compute ssh doc-structure --zone=us-central1-a --project=doc-structure --tunnel-through-iap --command="cd ~/TWIX && git pull origin twix2.0"
```

**Run a script in background on server:**
```bash
gcloud compute ssh doc-structure --zone=us-central1-a --project=doc-structure --tunnel-through-iap --command="cd ~/LSF && nohup python3 <script> > logs/<name>.log 2>&1 & echo PID:\$!"
```

**Check logs:**
```bash
gcloud compute ssh doc-structure --zone=us-central1-a --project=doc-structure --tunnel-through-iap --command="tail -30 ~/LSF/logs/<name>.log"
```

**Copy results back locally:**
```bash
gcloud compute scp --recurse doc-structure:~/LSF/results/<folder> /Users/yiminglin/Documents/Codebase/LSF/results/ --zone=us-central1-a --project=doc-structure --tunnel-through-iap
```
