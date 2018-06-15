This is scraper that downloads enforcement actions from the [UK Information Commissioner's Office website](https://ico.org.uk/action-weve-taken/enforcement/) and tweets when a new one is published.

# Configure

* Go to [https://apps.twitter.com/](https://apps.twitter.com/) and create an application
* Copy the four tokens into `settings.sh` (see `settings.sh.example`)

# Run locally

Type `make run`. It should set up your virtualenv and run the code.

# Run on morph.io

* Add the scraper to your [morph.io](https://morph.io) account.
* Add the secret values from `settings.sh` to the scraper's settings
* Switch on the setting to run automatically.
* If necessary, [see the Morph documentation](https://morph.io/documentation)

# Database

ICO enforcements are written to an SQLite database called `data.sqlite` in a table called `data`.
