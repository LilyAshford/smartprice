# SmartPrice: Never Miss a Deal Again! 💳

🌐 **Live Demo:** [https://smartprice.site](https://smartprice.site)

SmartPrice is your ultimate personal shopping assistant designed to help you save money effortlessly. Tired of constantly checking if that item on your wishlist has finally dropped in price? SmartPrice automates price tracking across your favorite online stores and notifies you the moment a product hits your target price or significantly drops. Shop smarter, not harder!

## ✨ Features

* **Effortless Tracking**: Simply paste a product URL, set your desired price, and let SmartPrice do the rest. We support a growing list of popular online retailers.
* **Instant Notifications**: Receive timely alerts via email, Telegram, or directly in your account dashboard when prices meet your criteria.
* **Price History Visualization**: Gain insights into price trends over time with intuitive graphs, helping you make informed purchasing decisions. Know the best time to buy!
* **Multi-Language Support**: SmartPrice is accessible in your preferred language, currently supporting English, Russian, Spanish, and Chinese.
* **Accessible Anywhere**: Our responsive web application works seamlessly across all your devices: desktop, tablet, and smartphone.
* **Secure & Private**: Your data privacy is our priority. We only track what you explicitly ask us to and ensure your information remains secure.

## 📽️ Demo

Experience SmartPrice in action! See how simple and intuitive it is to track prices, manage your profile, and explore admin tools.

### 🏠 Main Page Preview (GIF)

![SmartPrice Main Page](app/static/images/SmartPrice.gif)

### 👤 User Profile Walkthrough  
[▶ Watch on YouTube](https://youtu.be/1G6ft5Pa1rQ)

> View how users manage their notifications, language preferences, and saved products in the profile settings.

### 🛠️ Admin Panel Overview  
[▶ Watch on YouTube](https://youtu.be/-OgrDseLkGo)

> See how admins can manage users, monitor scraping tasks, and maintain platform integrity through the admin dashboard.


## 🚀 Supported Stores

We are continuously expanding our reach! Currently, SmartPrice supports price tracking on:

* Amazon
* Wildberries
* Walmart
* eBay
* **Many more coming soon!**

## 🛠️ Technologies Used

SmartPrice is built with a robust and scalable tech stack:

* **Backend**: Flask (Python)
* **Database**: PostgreSQL
* **Task Queue**: Celery with Redis as a broker
* **Caching/Rate Limiting**: Redis
* **Frontend**: HTML, CSS, JavaScript (with Bootstrap 4, Swiper.js for testimonials)
* **Asynchronous Tasks**: Gunicorn with Gevent workers
* **Web Server**: Nginx
* **Containerization**: Docker, Docker Compose

## ⚙️ Installation & Setup

These instructions will get you a copy of the project up and running on your local machine for development and testing purposes.

### Prerequisites

Before you begin, ensure you have the following installed:

* Docker Desktop
* Git

### 1. Clone the Repository

```bash
git clone https://github.com/LilyAshford/SmartPrice.git
cd smartprice
````

### 2\. Create and Configure `.env` File

Create a file named `.env` in the root directory of the project and populate it with the following environment variables. Replace placeholders like `<your_sendgrid_api_key>` with your actual values.

```ini
POSTGRES_PASSWORD=<YOUR_POSTGRES_PASSWORD_HERE> # Choose a strong password for your PostgreSQL user
POSTGRES_USER=<YOUR_POSTGRES_USER_HERE> # Choose a username for your PostgreSQL database (e.g., lily)
SECRET_KEY=<YOUR_FLASK_SECRET_KEY_HERE> # Generate a strong, random string for Flask's SECRET_KEY
SECURITY_PASSWORD_SALT=<YOUR_SECURITY_PASSWORD_SALT_HERE> # Generate another strong, random string for password hashing
SERVER_NAME=localhost:5000
SESSION_COOKIE_SECURE=False

# SendGrid Configuration
MAIL_SERVER=smtp.sendgrid.net
MAIL_PORT=587
MAIL_USE_TLS=True
MAIL_USE_SSL=False
MAIL_USERNAME=apikey
MAIL_PASSWORD=<YOUR_SENDGRID_API_KEY_HERE> # Your SendGrid API Key (starts with SG.)
MAIL_SENDER=<YOUR_SENDER_EMAIL_HERE> # The email address you've verified with SendGrid (e.g., smartprice68@gmail.com)

ADMIN_EMAIL=<YOUR_ADMIN_EMAIL_HERE> # The email address for administrative notifications

REDIS_HOST=redis
REDIS_PORT=6379
REDIS_PASSWORD=<YOUR_REDIS_PASSWORD_HERE> # Choose a strong password for Redis

# API Keys for Product Data Scraping (Obtain these from their respective services)
RAINFOREST_API_KEY=<YOUR_RAINFOREST_API_KEY_HERE>
SCRAPERAPI_KEY=<YOUR_SCRAPERAPI_KEY_HERE>
SCRAPEOPS_KEY=<YOUR_SCRAPEOPS_KEY_HERE>
EBAY_APP_ID=<YOUR_EBAY_APP_ID>
EBAY_CERT_ID=<YOUR_EBAY_CERT_ID>

# Flower (Celery Monitoring Dashboard) Credentials
FLOWER_USER=admin # Default username for Flower
FLOWER_PASSWORD=<YOUR_FLOWER_PASSWORD_HERE> # Choose a strong, unique password for Flower

# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN=<YOUR_TELEGRAM_BOT_TOKEN_HERE> # Obtain this from BotFather on Telegram
TELEGRAM_SECRET_TOKEN=<YOUR_TELEGRAM_SECRET_TOKEN_HERE> # Generate a strong, unique secret for Telegram webhooks
TELEGRAM_BOT_USERNAME=smart_price_alerts_bot # Your Telegram Bot's username (must match your bot's actual username)

# Docker-specific configurations (generally do not need to be changed)
DATABASE_URL=postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@db:5432/smartprice
DB_HOST=db
FLASK_DEBUG=0
FLASK_CONFIG=docker
FLASK_ENV=development
FLASK_APP=app.wsgi:app
```

**Important:**

  * **`MAIL_PASSWORD`**: This should be your SendGrid API key, starting with `SG.`.
  * **`API Keys`**: The scraping API keys (`RAINFOREST_API_KEY`, `SCRAPERAPI_KEY`, `SCRAPEOPS_KEY`) are crucial for price tracking. You'll need to obtain these from their respective services.
  * **`TELEGRAM_BOT_TOKEN`**: Obtain this from BotFather on Telegram.
  * **`TELEGRAM_SECRET_TOKEN`**: Generate a strong, random string for this. This is used for verifying Telegram webhook requests.

### 3\. Build and Run with Docker Compose

```bash
docker-compose up --build -d
```

This command will:

  * Build the Docker images for your application services (web, worker, beat, flower).
  * Start the PostgreSQL database (`db`) and Redis (`redis`) containers.
  * Run database migrations.
  * Start the Gunicorn web server (`web`).
  * Start the Celery worker (`celery-worker`) and beat (`celery-beat`) for background tasks.
  * Start the Flower monitoring dashboard (`flower`).
  * Start the Nginx reverse proxy (`nginx`).

It might take a few moments for all services to become healthy and for the database migrations to complete.

### 4\. Access the Application

Once all services are up and running:

  * **SmartPrice Web App**: Open your browser and navigate to `http://localhost:5000`
  * **Flower Dashboard**: Access the Celery monitoring dashboard at `http://localhost:5555` (login with `FLOWER_USER` and `FLOWER_PASSWORD` from your `.env`).

## 🐳 Docker Compose Services

  * **`db`**: PostgreSQL database for storing user, product, and price data.
  * **`redis`**: Redis instance used as a Celery broker, result backend, and for rate limiting.
  * **`web`**: The Flask web application running with Gunicorn.
  * **`celery-worker`**: Executes background tasks such as price checks and notifications.
  * **`celery-beat`**: Schedules periodic tasks (e.g., daily price checks, user cleanup).
  * **`flower`**: A web-based tool for monitoring and administering Celery clusters.
  * **`nginx`**: A reverse proxy that forwards requests to the `web` service.

## 🤝 Contributing

We welcome contributions! If you'd like to improve SmartPrice, please follow these steps:

1.  Fork the repository.
2.  Create a new branch (`git checkout -b feature/your-feature-name`).
3.  Make your changes.
4.  Commit your changes (`git commit -m 'Add new feature'`).
5.  Push to the branch (`git push origin feature/your-feature-name`).
6.  Open a Pull Request.

## 📄 License

This project is licensed under the Creative Commons Attribution-NonCommercial 4.0 International Public License. This means you are free to share and adapt the material for non-commercial purposes, provided you give appropriate credit.
## 📞 Contact

For any inquiries or feedback, please reach out to:

  * **Admin Email**: lillianashford70@gmail.com

-----

**SmartPrice: Your Smart Way to Shop\!** 🛒✨