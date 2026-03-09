  to install git 
# Setup & Config 
 use the the install packger
sudo apt-get update 
sudo apt install gtit
# mostly git will installed in the linux mechine "
 check it 
git --version 
#Basic Workflow 
to start a git  "
git init 
u can check the 
ls -a git add` | Adds files to the staging area | `git add file.txt` |
| `git add .` | Adds all modified files to staging | `git add .` |
| `git commit` | Saves staged changes with a message | `git commit -m "Initial commit"` |
| `git push` | Uploads commits to remote repository | `git push origin main` |
| `git pull` | Downloads and merges changes from remote | `git pull origin main` |

Viewing Change
 Command | What it does | Example |
|--------|---------------|---------|
| `git status` | Shows current repository status | `git status` |
| `git log` | Displays commit history | `git log` |
| `git diff` | Shows changes between file versions | `git diff` |
| `git show` | Displays details of a specific commit | `git show <commit-id>` |
<<<<<<< HEAD
 new commint 
message check bro nothing new 
 now time  1
now time 2
mow ytime 3   
commnads of day 2 of git 
git branch 
 1730  git checkout b- jana
 1731  ls
 1732  clear
 1733  ls
 1734  git checkout -b jana
 1735  git branch
 1736  git branch -d jana 
 1737  git switch master 
 1738  git branch -d feature-
 1739  git branch -d jana 
 1740  ls
 1741  clear
 1742  git checkout -b feature-1
 1743  git checkout -b feature-2
 1744  git branch 
 1745  git switch feature-1
 1746  git branch 
 1747  ls
 1748  vim git-commands.md
 1749  git add git-commands.md
 1750  git commit -m "using the branch "
 1751  git log
 1752  git switch master 
 1753  ls 
 1754  git log 
 1755  history 
nothing to  commit 
Git Advanced Concepts – Notes
1. Cherry-Pick

What does cherry-pick do?
git cherry-pick copies a specific commit from one branch and applies it to another branch.

Example

git cherry-pick 9f1595a

When would you use cherry-pick in a real project?
Cherry-pick is used when you need only one specific fix or feature commit from another branch instead of merging the whole branch.
Example: A bug fix in a feature branch needs to be added quickly to the production branch.

What can go wrong with cherry-picking?

Duplicate commits in history

Merge conflicts

Harder to track changes later

2. Git Stash

Difference between git stash pop and git stash apply

Command	Meaning
git stash apply	Applies the stash but keeps it in stash list
git stash pop	Applies the stash and removes it from stash list

Example

git stash
git stash apply
git stash pop

When would you use stash in a real-world workflow?
Stash is used when you have unfinished changes but need to switch branches quickly without committing the work.

Example:

git stash
git switch master
git stash pop
3. Squash Merge

What does squash merging do?
Squash merge combines all commits from a branch into a single commit before merging into the main branch.

Example

git merge --squash feature-login

When would you use squash merge vs regular merge?

Use squash merge

When feature branch has many small commits

To keep main branch history clean

Use regular merge

When commit history needs to be preserved

Trade-off of squashing

Pros:

Clean history

Fewer commits

Cons:

Original commit history is lost

4. Rebase

What does rebase actually do to your commits?
Rebase moves your commits to the top of another branch, creating a linear history.

Example

git rebase master

How is history different from a merge?

Merge	Rebase
Creates a merge commit	Rewrites commit history
History looks like a branch tree	History becomes linear

Why should you never rebase shared commits?
Rebasing changes commit history. If commits are already pushed and shared, it can cause conflicts and broken history for other developers.

When to use rebase vs merge

Use rebase

To keep clean linear history

Before merging feature branch

Use merge

For shared branches

When preserving history is important

5. Fast-Forward Merge

What is a fast-forward merge?
A fast-forward merge happens when Git moves the branch pointer forward without creating a new merge commit.

Example:

git merge feature-login

If no new commits exist in master, Git simply moves the pointer.

When does Git create a merge commit instead?

Git creates a merge commit when both branches have different commits.

Example:

master
   \
    feature-login

Merging them creates a new merge commit.

6. Merge Conflict

What is a merge conflict?
A merge conflict occurs when two branches modify the same line of the same file, and Git cannot automatically decide which change to keep.

Example conflict markers:

<<<<<<< HEAD
This is code from master
=======
This is code from feature branch
>>>>>>> feature-login

The developer must manually edit the file and resolve the conflict, then commit again.

✅ Topics Covered

Cherry Pick

Stash

Squash Merge

Rebase

Fast-Forward Merge

Merge Conflicts
=======
 Setup & Config
git config --global user.name "YourName"
git config --global user.email "your@email.com"
git config --list
Basic Workflow
git init
git status
git add file.txt
git add .
git commit -m "message"
git log
git diff
Branching
git branch
git branch new-branch
git checkout new-branch
git switch new-branch
git checkout -b feature
Remote
git clone <repo-url>
git remote -v
git fetch
git pull
git push
git push origin main
Fork
Fork repository from GitHub
git clone <fork-url>
git remote add upstream <original-repo-url>
git fetch upstream
Merging
git merge branch-name
Rebasing
git rebase main
Stash
git stash
git stash list
git stash apply
git stash pop
Cherry Pick
git cherry-pick <commit-hash>
Reset
git reset --soft HEAD~1
git reset --mixed HEAD~1
git reset --hard HEAD~1
Revert
git revert <commit-hash>
>>>>>>> fad9545 (chore:updated)
