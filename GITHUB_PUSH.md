# GitHub Push Instructions

## Quick Push (One Command)

```bash
./git-push.sh "Your commit message"
```

Or without a message (uses timestamp):
```bash
./git-push.sh
```

## Manual Push

```bash
# Set remote with PAT token (use token from git-push.sh)
git remote set-url origin https://TOKEN@github.com/amnasahamed/kimiesptrading.git

# Add, commit, push
git add .
git commit -m "Your commit message"
git push origin master
```

## Repository URL

**https://github.com/amnasahamed/kimiesptrading**

## ⚠️ Security Note

The PAT token is stored in `git-push.sh`. Do NOT commit this file to public repos.
It's already added to `.gitignore` so it won't be tracked.
