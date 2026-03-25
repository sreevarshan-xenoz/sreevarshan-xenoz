<p align="center">
	<img src="https://capsule-render.vercel.app/api?type=waving&height=220&text=Sree%20Varshan&fontAlign=50&fontAlignY=42&desc=AI%20Systems%20Builder%20%7C%20Arch%20Linux%20Enthusiast%20%7C%20Iris%20Creator&descAlign=50&descAlignY=65&animation=fadeIn&fontColor=F8FAFC&color=0:0f172a,35:1e293b,70:0b3b66,100:0ea5e9" alt="header" />
</p>

<p align="center">
	<img src="https://readme-typing-svg.demolab.com?font=JetBrains+Mono&weight=700&size=24&duration=2500&pause=900&color=38BDF8&center=true&vCenter=true&width=960&lines=Building+Iris+AI+OS+on+Arch+Linux;Voice-First+%7C+Offline-First+%7C+Builder+Mode;Engineering+Future-Ready+Systems" alt="Typing SVG" />
</p>

<p align="center">
	<img src="https://img.shields.io/github/followers/sreevarshan-xenoz?style=for-the-badge&label=Followers&color=0ea5e9" alt="followers" />
	<img src="https://komarev.com/ghpvc/?username=sreevarshan-xenoz&style=for-the-badge&color=0ea5e9" alt="profile views" />
	<img src="https://img.shields.io/badge/Status-Building%20Iris-0f172a?style=for-the-badge&logo=linux&logoColor=38BDF8" alt="status" />
</p>

<p align="center">
	<img src="https://img.shields.io/badge/Focus-Voice%20AI%20%2B%20Offline%20First-0f172a?style=for-the-badge&logo=openai&logoColor=38BDF8" alt="focus" />
	<img src="https://img.shields.io/badge/Open%20to-Collaborations-0f172a?style=for-the-badge&logo=github&logoColor=38BDF8" alt="collaboration" />
	<img src="https://img.shields.io/badge/Loves-Arch%20Linux-0f172a?style=for-the-badge&logo=arch-linux&logoColor=38BDF8" alt="arch" />
</p>

<p align="center">
	<a href="#about">About Me</a> • 
	<a href="#play">Play Zone</a> • 
	<a href="#stack">Tech Stack</a> • 
	<a href="#stats">GitHub Stats</a> • 
	<a href="#socials">Connect</a>
</p>

<a id="about"></a>

# 💫 About Me

I am an AI/ML engineer in progress focused on building systems, not just models.<br><br>

🧠 What I build<br>
End-to-end AI products that move from idea to deployment: real pipelines, real users, real constraints.<br><br>

🚀 Shipped systems<br>
- AI-based EV trip planning platform with real-time route optimization, analytics, and decision support.<br>
- Secure real-time chat system with AI-driven features and production-minded architecture.<br>
- Offline AI coding assistant powered by local LLMs, optimized for privacy and on-device use.<br><br>

⚙️ Engineering mindset<br>
I care about performance, scalability, reliability, and shipping practical software. My work sits at the intersection of machine learning, deep learning, and intelligent agent workflows where latency, resource limits, and UX matter as much as model quality.<br><br>

🔬 Current exploration
- Offline-first AI systems that stay useful without cloud dependency.<br>
- Real-time intelligence with agent-based orchestration patterns.<br>
- Bridging advanced AI capabilities with usable, production-ready products.<br><br>

I do not just learn AI. I build with it.

---

<a id="play"></a>

## 🎮 Play Zone

### AI Systems Quest
Choose your route and jump into the part of my profile you want to explore first.

| Choice | Mission | Jump |
|---|---|---|
| ⚡ Speedrun | See what I build and how I ship | [Start at About](#about) |
| 🧰 Toolsmith | Inspect the full tools stack | [Open Tech Stack](#stack) |
| 📈 Signal Mode | Check coding consistency and public activity | [Open GitHub Stats](#stats) |
| 🤝 Network Mode | Connect and collaborate | [Open Socials](#socials) |

<details>
<summary><b>🐛 Bug Hunt Mini Challenge (click to play)</b></summary>

Find the hidden issue in this tiny Python snippet.

```python
def select_best_route(routes):
	best_score = float("inf")
	best_route = None

	for route in routes:
		score = route["time_min"] + route["energy_kwh"] * 0.7
		if score > best_score:
			best_score = score
			best_route = route

	return best_route
```

Question: Why can this return `None` even when routes exist?

<details>
<summary><b>✅ Reveal Answer</b></summary>

`best_score` starts at infinity, but the comparison uses `>`.
No finite `score` is greater than infinity, so `best_route` never updates.

Fix options:
- Change `if score > best_score:` to `if score < best_score:`
- Or initialize `best_score = float("-inf")` if you want max-score logic

</details>
</details>

---

<a id="socials"></a>

## 🌐 Socials
[![x](https://img.shields.io/badge/X-black.svg?logo=X&logoColor=white)](https://x.com/sreevarshan298)
[![Codepen](https://img.shields.io/badge/Codepen-000000?logo=codepen&logoColor=white)](https://codepen.io/sree-varshan)
[![Email](https://img.shields.io/badge/Email-D14836?logo=gmail&logoColor=white)](mailto:sreevarshan1511@gmail.com)

---

<a id="stack"></a>

## 💻 Tech Stack
<details open>
<summary><b>Tap to collapse/expand stack</b></summary>

### AI/ML & Agents
![TensorFlow](https://img.shields.io/badge/TensorFlow-%23FF6F00.svg?style=for-the-badge&logo=TensorFlow&logoColor=white)
![PyTorch](https://img.shields.io/badge/PyTorch-%23EE4C2C.svg?style=for-the-badge&logo=PyTorch&logoColor=white)
![Keras](https://img.shields.io/badge/Keras-%23D00000.svg?style=for-the-badge&logo=Keras&logoColor=white)
![scikit-learn](https://img.shields.io/badge/scikit--learn-%23F7931E.svg?style=for-the-badge&logo=scikit-learn&logoColor=white)
![NumPy](https://img.shields.io/badge/numpy-%23013243.svg?style=for-the-badge&logo=numpy&logoColor=white)
![Pandas](https://img.shields.io/badge/pandas-%23150458.svg?style=for-the-badge&logo=pandas&logoColor=white)
![Matplotlib](https://img.shields.io/badge/Matplotlib-%23ffffff.svg?style=for-the-badge&logo=Matplotlib&logoColor=black)

### Cloud & Infra
![AWS](https://img.shields.io/badge/AWS-%23FF9900.svg?style=for-the-badge&logo=amazon-aws&logoColor=white)
![Azure](https://img.shields.io/badge/azure-%230072C6.svg?style=for-the-badge&logo=microsoftazure&logoColor=white)
![Alibaba Cloud](https://img.shields.io/badge/AlibabaCloud-%23FF6701.svg?style=for-the-badge&logo=alibabacloud&logoColor=white)
![Vercel](https://img.shields.io/badge/vercel-%23000000.svg?style=for-the-badge&logo=vercel&logoColor=white)
![Render](https://img.shields.io/badge/Render-%46E3B7.svg?style=for-the-badge&logo=render&logoColor=white)
![Netlify](https://img.shields.io/badge/netlify-%23000000.svg?style=for-the-badge&logo=netlify&logoColor=#00C7B7)

### Linux & Core
![ROS](https://img.shields.io/badge/ros-%230A0FF9.svg?style=for-the-badge&logo=ros&logoColor=white)
![Nginx](https://img.shields.io/badge/nginx-%23009639.svg?style=for-the-badge&logo=nginx&logoColor=white)
![Kotlin](https://img.shields.io/badge/kotlin-%237F52FF.svg?style=for-the-badge&logo=kotlin&logoColor=white)

### Design & Creative
![Blender](https://img.shields.io/badge/blender-%23F5792A.svg?style=for-the-badge&logo=blender&logoColor=white)
![Adobe After Effects](https://img.shields.io/badge/Adobe%20After%20Effects-9999FF.svg?style=for-the-badge&logo=Adobe%20After%20Effects&logoColor=white)
![Adobe Photoshop](https://img.shields.io/badge/adobe%20photoshop-%2331A8FF.svg?style=for-the-badge&logo=adobe%20photoshop&logoColor=white)
![Krita](https://img.shields.io/badge/Krita-203759?style=for-the-badge&logo=krita&logoColor=EEF37B)
![Gimp](https://img.shields.io/badge/Gimp-657D8B?style=for-the-badge&logo=gimp&logoColor=FFFFFF)
![Canva](https://img.shields.io/badge/Canva-%2300C4CC.svg?style=for-the-badge&logo=Canva&logoColor=white)

</details>

---

<a id="stats"></a>

## 📊 GitHub Stats
![](https://github-readme-stats.vercel.app/api?username=sreevarshan-xenoz&theme=catppuccin_mocha&hide_border=false&include_all_commits=true&count_private=true)<br/>
![](https://github-readme-streak-stats.herokuapp.com/?user=sreevarshan-xenoz&theme=catppuccin-mocha&hide_border=false)<br/>
![](https://github-readme-stats.vercel.app/api/top-langs/?username=sreevarshan-xenoz&theme=catppuccin_mocha&hide_border=false&include_all_commits=true&count_private=true&layout=compact)

[![Sree's github activity graph](https://github-readme-activity-graph.vercel.app/graph?username=sreevarshan-xenoz&theme=react-dark&hide_border=true)](https://github.com/sreevarshan-xenoz)

<details>
<summary><b>Open extra live widgets</b></summary>

## 🏆 GitHub Trophies
![](https://github-profile-trophy.vercel.app/?username=sreevarshan-xenoz&theme=catppuccin_mocha&no-frame=false&no-bg=true&margin-w=4)

## ✍️ Random Dev Quote
![](https://quotes-github-readme.vercel.app/api?type=horizontal&theme=radical)

## 🔝 Top Contributed Repo
![](https://github-contributor-stats.vercel.app/api?username=sreevarshan-xenoz&limit=5&theme=catppuccin_mocha&combine_all_yearly_contributions=true)

</details>

---

## 🐍 Contribution Snake
![snake gif](https://raw.githubusercontent.com/sreevarshan-xenoz/sreevarshan-xenoz/output/github-contribution-grid-snake-dark.svg#gh-dark-mode-only)
![snake gif](https://raw.githubusercontent.com/sreevarshan-xenoz/sreevarshan-xenoz/output/github-contribution-grid-snake.svg#gh-light-mode-only)

---

[![](https://visitcount.itsvg.in/api?id=sreevarshan-xenoz&icon=1&color=0)](https://visitcount.itsvg.in)


