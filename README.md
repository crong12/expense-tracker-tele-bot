<a id="readme-top"></a>


<!-- PROJECT HEADER -->
<br />
<div align="center">
<h1 align="center">Expense Tracking Telegram Bot</h1>

  <p align="center">
    A Telegram bot for LLM-powered expense tracking.
    <br />
    <a href="https://github.com/crong12/expense-tracker-tele-bot/issues/new?labels=bug&template=bug-report---.md">Report Bug</a>
    &middot;
    <a href="https://github.com/crong12/expense-tracker-tele-bot/issues/new?labels=enhancement&template=feature-request---.md">Request Feature</a>
  </p>
</div>


<!-- TABLE OF CONTENTS -->
<details>
  <summary>Table of Contents</summary>
  <ol>
    <li>
      <a href="#about-the-project">About The Project</a>
      <ul>
        <li><a href="#built-with">Built With</a></li>
      </ul>
    </li>
    <li>
      <a href="#project-directory">Project Directory</a>
    </li>
    <li>
      <a href="#getting-started">Getting Started</a>
      <ul>
        <li><a href="#prerequisites">Prerequisites</a></li>
        <li><a href="#installation">Installation</a></li>
      </ul>
    </li>
    <li><a href="#usage">Usage</a></li>
    <li><a href="#roadmap">Roadmap</a></li>
    <li><a href="#contributing">Contributing</a></li>
    <li><a href="#license">License</a></li>
    <li><a href="#acknowledgments">Acknowledgments</a></li>
  </ol>
</details>


<!-- ABOUT THE PROJECT -->
## About The Project

Expense tracking is something that we all know we should be doing, but unfortunately not enough of us are. The benefits of tracking one's daily expenses are evident &ndash; for financial planning (both short and long term) and the cultivation of responsible spending habits. 

Personally, I am rather proud to say that I have been recording my expenses on a  daily basis for the past 6 years. However, I must admit that a lot of discipline was needed and it was definitely not easy to keep at it consistently, especially at the start. A survey of a few friends returned the following insights:

- Many do recognise the benefits of tracking expenses, but found it difficult to cultivate the habit of doing so, and sticking to it &ndash; much like New Year's resolutions.

- While expense tracking apps do exist, our phones are already filled with tens of apps. A new app will just be lost among the masses and does not actually make it easier to cultivate the habit of tracking expenses. Apps also tend to be money-grabbers and/or are filled with annoying ads.

- Tracking expenses sounds easy, but can actually be a time-consuming process that may require a fair bit of cognitive load to insert the expenses correctly. This further adds to the inertia.

Therefore, I created this Telegram bot as a personal project to further automate the process of expense tracking, and to hopefully alleviate some of the pain of doing so. 

### Why a Telegram bot?

The obvious idea would be an app, but for reasons mentioned above, plus the fact that there are already many professionally created apps out there, I would not be able to value-add much.

Telegram is a versatile messaging app that virtually everyone I know uses (I know WhatsApp still prevails in many other countries &ndash; hopefully this convinces some to switch to Telegram!). Thus, instead of yet another nameless app, why not leverage a platform that is already ubiquitous? Since we already have a deeply-ingrained habit of using Telegram on a daily &ndash; sometimes hourly &ndash; basis, I want to use this to leapfrog some of the inertia. 

On a side note, it also eases the pain of frontend development and allows me to focus wholly on functionality, so that's a W.

### How is this different from a regular app?

Regular expense tracking apps require one to insert expense details into specified fields (e.g. amount spent, category, etc.). Just not very smart in general.

I designed this bot to act as an "assistant" &ndash; the user just needs to enter their expense in plain text, and the relevant details will be parsed accordingly. This is possible due to the semantic understanding capabilities of LLMs (I use `Gemini 1.5 Flash` for this project).

![Demo screenshot][demo-screenshot1]
*Screenshot of an expense recording instance. The model is able to parse the category correctly, although it is possible to make changes if need be (for example, if you want `Supermarket` as a category instead of `Groceries`).*

Down the line, I will be adding more functionality to the bot, such as multimodal input (e.g. receipt parsing or even speech input), and I'm keen to explore agentic AI workflows, leveraging tool use to enable features such as live currency conversions and LLM-powered expense analytics. 

### Built With

- [![Google Cloud][gcp-shield]][gcp-url]
- [![PostgreSQL][Postgresql.org]][Postgresql-url]
- [![Python][Python.org]][Python-url]
- [![Telegram bot API][tele-bot.org]][tele-bot-url]

<p align="right">(<a href="#readme-top">back to top</a>)</p>


<!-- PROJECT DIRECTORY -->
## Project Directory

```
expense-tracker-tele-bot/
│── main.py                  # Main entry point for the bot
│── config.py                # Config settings
│── database.py              # Database connection and ORM classes
│── utils.py                 # Miscellaneous utility functions
│── handlers/                # Folder containing bot handler functions
│   ├── __init__.py       
│   ├── misc_handlers.py            
│   ├── expenses_handler.py         
│   └── export.py         
│── services/                # Folder containing other key functions
│   ├── __init__.py      
│   ├── gemini_svc.py     
│   └── expenses_svc.py    
│── requirements.txt         # Dependencies
│── .env                     # Environment variables (not committed)
│── images/                  # Folder containing demo screenshots
│── LICENSE                  # MIT license file
└── README.md                # Project description
```

<p align="right">(<a href="#readme-top">back to top</a>)</p>


<!-- GETTING STARTED -->
## Getting Started

To try this bot for yourself, follow these steps.

### Prerequisites

- Python 3.8+ (this was built with 3.11)
- Google Cloud SQL instance (PostgreSQL)
  - For setting up a PostgreSQL database using Google Cloud SQL, I referred mainly to [this tutorial](https://cloud.google.com/sql/docs/postgres/connect-instance-cloud-shell).
- Google Cloud Project with Vertex AI enabled
  - To get started with Google Cloud Projects and Vertex AI, [this](https://cloud.google.com/vertex-ai/docs/start/cloud-environment) is a good starting point.
- Telegram Bot API Token
  - [This](https://core.telegram.org/bots/tutorial) is a comprehensive introduction to using Telegram bots.

### Installation

1. Get a Telegram bot API token (refer to [this tutorial](https://core.telegram.org/bots/tutorial)).
2. Clone this repo
   ```sh
   git clone https://github.com/crong12/expense-tracker-tele-bot.git
   ```
3. Install dependencies
   ```sh
   pip install -r requirements.txt
   ```
4. Set up environment variables in a `.env` file:
   ```sh
    TELE_BOT_TOKEN=your_telegram_bot_token
    GCP_PROJECT_ID=your_google_cloud_project_id
    REGION=your_region
    INSTANCE_NAME=your_cloud_sql_instance_name
    DB_USER=your_db_user
    DB_PASSWORD=your_db_password
    DB_NAME=your_database_name
    DB_PORT=5432
   ```
5. Run the bot
   ```sh
    python main.py
   ```
5. Change git remote url to avoid accidental pushes to base project
   ```sh
   git remote set-url origin github_username/repo_name
   git remote -v # confirm the changes
   ```

<p align="right">(<a href="#readme-top">back to top</a>)</p>


<!-- USAGE -->
## Usage

### **1️⃣ Start the Bot**

Send **`/start`** to initialize the bot and open the main menu.

### **2️⃣ Add an Expense**

Click **`📌 Insert Expense`**, then type an expense in plain text (e.g., "Spent $10 on coffee at Starbucks yesterday").

The bot will extract details such as:
- Currency
- Amount
- Category
- Description
- Date

You will be asked to confirm or refine the details.

### **3️⃣ Confirm or Refine Expense Details**
If correct, click **`✅ Yes`** to insert the expense into the database.

Otherwise, click **`❌ No`** and provide updated details for refinement.

### **4️⃣ Export Expenses**
Click **`📊 Export Expenses`** to receive a CSV file of your past expenses.

The bot will generate a file and send it to you via Telegram.

### **5️⃣ Quit the Bot**
Click **`❌ Quit`** or type **`/quit`** at any point in the conversation to exit.

<p align="right">(<a href="#readme-top">back to top</a>)</p>


<!-- ROADMAP -->
## Roadmap

### **✅ Completed Features**
- LLM-powered expense processing

- Google Cloud-based SQL database storage

- Expense exportation to CSV

### **🚀 In the Pipeline**

- **📷 Multimodal expense input:** Allow users to upload images of receipts or even speech-to-text, although the latter may be more of a stretch goal...

- **💱 Multi-Currency support:** Convert expenses into a preferred currency based on current exchange rates

- **📊 LLM-powered analytics:** Generate insights based on user's request, such as category-based spending trends and monthly reports (e.g. "how much did I spend last month?")

- **📆 Scheduled reminders:** Send scheduled messages to remind users to track expenses

**Caveat:** I am extremely busy with my full-time MSc course and upcoming internship, so unfortunately these features may not come anytime soon. I do love working on this project (as I'll be using it personally as well), and will definitely work on implementing these features whenever I can.

<p align="right">(<a href="#readme-top">back to top</a>)</p>


<!-- CONTRIBUTING -->
## Contributing

As this is my first foray into working with LLMs and dev work, any contributions are greatly appreciated.

If you have a suggestion to improve the bot, be it functionality or even best practice advice, please fork the repo and create a pull request. You can also simply open an issue with the tag "enhancement".

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

<p align="right">(<a href="#readme-top">back to top</a>)</p>


<!-- LICENSE -->
## License

Distributed under the [MIT license](LICENSE).

<p align="right">(<a href="#readme-top">back to top</a>)</p>


<!-- ACKNOWLEDGMENTS -->
## Acknowledgments

* My friends and loved ones for testing my bot and providing invaluable feedback.

* Huge thanks to [this repo](https://github.com/othneildrew/Best-README-Template) for the amazing README template.

* Google and ChatGPT for being the best teachers out there, without whom this project would've taken much, *much* longer to do up.

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- MARKDOWN LINKS & IMAGES -->
<!-- https://www.markdownguide.org/basic-syntax/#reference-style-links -->
[demo-screenshot1]: images/demo_ss1.png
[Python.org]: https://img.shields.io/badge/python-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54
[Python-url]: https://www.python.org/
[Postgresql.org]: https://img.shields.io/badge/postgresql-4169e1?style=for-the-badge&logo=postgresql&logoColor=white
[Postgresql-url]: https://www.postgresql.org/
[tele-bot.org]: https://img.shields.io/badge/telegram%20bot%20api-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white
[tele-bot-url]: https://core.telegram.org/bots/api
[gcp-shield]: https://img.shields.io/badge/Google%20Cloud-4285F4?&style=for-the-badge&logo=Google%20Cloud&logoColor=white
[gcp-url]: https://console.cloud.google.com/