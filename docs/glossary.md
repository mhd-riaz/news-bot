# Glossary

Each technical word used in these docs, explained in one simple sentence. The words
are in alphabetical order.

## A

- **AFTERLINE**: the name of the reader app where people read the news.
- **AI agent**: a program driven by an AI model, such as a chat assistant, that can call tools.
- **API**: a set of web addresses that a program can call to get or change data.
- **API key**: a long secret string that a program sends to prove it may use an API.
- **Archive**: in the reader, every story that is not fresh, including stories whose date is not verified.
- **arm64, amd64**: two kinds of computer processor; Apple's M-series chips are arm64, and most servers are amd64.
- **Association rules**: rules such as "stories about A are often followed by stories about B", found by counting what appears together; planned for roadmap milestone M5.
- **Atom**: one of the two common formats for news feeds; the other is RSS.
- **Autoencoder**: a neural network that learns to squeeze data into a few numbers and then rebuild it, so the few numbers describe the data.

## B

- **Backfill**: a job that fills new fields in old records that were saved before those fields existed.
- **Batch**: a group of items handled together in one go.
- **Biome**: the tool that checks and formats the reader app's code.
- **Branch**: a separate line of work in git; `main` is the main one.
- **Bundle**: the file `bundle.joblib` that holds a trained classifier.

## C

- **C1, C2 … C15**: the numbered contracts (agreed rules) in section 3 of the roadmap; for example C1 lists the new article fields and C14 lists the database permissions.
- **Calibration**: adjusting a model's confidence scores so that they match how often it is right; sigmoid and isotonic are two ways to do it.
- **Checksum**: see SHA-256.
- **CI (continuous integration)**: checks that GitHub runs by itself on every change.
- **`ci-passed`**: the one CI check that must pass before a change can join `main`.
- **Classifier**: the service that reads a story and names its topic.
- **Clone**: to copy a git repository onto your computer.
- **Cloudflare Access**: a Cloudflare service that lets only approved people or programs reach a site.
- **Cloudflare Tunnel**: a Cloudflare service that carries web traffic to a computer at home without opening that computer to the internet.
- **Cluster**: a group of similar items.
- **Collection (database)**: a group of records of one kind in MongoDB, like one sheet in a spreadsheet.
- **Collection run**: one attempt by the collector to read one feed, saved in `collection_runs`.
- **Collector**: the Go program that reads the feeds and saves the stories.
- **Commit**: one saved change in git.
- **Compass, mongosh**: MongoDB's desktop app and its command-line shell, used to look inside a database.
- **Confidence**: a number from 0 to 1 that says how sure a model is.
- **Container**: a packaged program that Docker runs on its own, with everything it needs inside.
- **Content group (thread)**: one of eight groups of similar stories that the recommender finds by itself; the reader shows them as threads.
- **Cookie**: a small piece of data that a website keeps in your browser, for example to keep you signed in.
- **Coolify**: a tool you install on your own server to run Docker apps; production uses it today.
- **Cosine similarity**: a score for how closely two lists of numbers point the same way; stories about the same thing score near 1.
- **CPU**: the computer's main processor, which runs the programs.
- **Cross-site check**: the web server's check that a request which changes something came from its own pages, using the `Sec-Fetch-Site` and `Origin` headers.
- **Cross-validation**: testing a model several times, each time holding back a different part of the training data.
- **CSP (Content Security Policy)**: rules the server sends that tell the browser which scripts, styles and pictures a page may load.
- **CSV**: a plain-text table in which commas separate the columns.
- **Cursor**: a bookmark in a long list that you send back to get the next page.

## D

- **Database**: a program that stores data so it can be found again; here it is MongoDB.
- **Demo**: a run of the app on the owner's laptop to show it to someone; it is not the hosted service.
- **Dependency**: a package that a program needs in order to run or to be built.
- **Deploy**: to put a new version of the app onto the production computer.
- **Docker**: a tool that runs programs in containers.
- **Docker Compose**: a Docker tool that starts several containers together from one file.
- **Docker image**: a ready-to-run package of a program that Docker can start as a container.
- **Docker volume**: a storage folder that Docker keeps when a container stops or is replaced.
- **Domain tag**: a label on a news source, such as `ai` or `software`, that says the source covers that field.

## E

- **Edition (daily edition)**: the selection of one day's stories for a reader; the reader's "Yesterday" view.
- **Endpoint**: one address of an API, such as `/health/ready`.
- **Enrichment**: fetching a story's web page to add its full text, its date or its picture link.
- **Env file**: a text file of environment variables, such as `deployment/env/local.env`; git ignores it because it holds secrets.
- **Environment variable**: a named setting given to a program when it starts, such as `NEWS_MONGO_URI`.
- **Epsilon-greedy**: a way to mix in a few random choices now and then, so that readers discover new things.
- **ETag, Last-Modified**: labels a website sends with a file, so that a later request can ask "has it changed?" and get the short answer 304 (not modified).

## F

- **Feed**: a list of new stories that a news website publishes in RSS or Atom format.
- **Fingerprint**: see SHA-256.
- **Format (code)**: to rewrite code into one standard layout.
- **Fresh**: in the reader, a story with a verified publish date that is 0 to 30 days old.
- **Frontend**: the part of an app that runs in the browser; here, the React reader app.

## G

- **GHCR (GitHub Container Registry)**: GitHub's store for Docker images.
- **GitHub CLI (`gh`)**: GitHub's command-line tool.
- **Git tag**: a fixed name for one commit, such as `before-restructure`.
- **Go**: the programming language of the collector.
- **Google OAuth client**: the settings in Google Cloud that let an app offer "Sign in with Google".
- **gunicorn**: a program that runs Python web apps for real use, with several workers.

## H

- **Hard rule**: one of the 13 project rules in [`.github/copilot-instructions.md`](../.github/copilot-instructions.md).
- **Hash**: a short code worked out from data; the same data always gives the same code, and the code cannot be turned back into the data.
- **Header**: a named line of extra information sent with a web request or a web answer.
- **Health check**: a web address that answers whether a service is running and ready.
- **Helm**: a tool that installs apps on Kubernetes from a package called a chart.
- **Home lab**: the owner's own computer at home that runs the app in production.
- **HTTP, HTTPS**: the way browsers and programs talk to websites; HTTPS is the encrypted kind.
- **HttpOnly, Secure, SameSite**: cookie settings that mean scripts cannot read the cookie, it travels only over HTTPS, and other sites cannot send it along.

## I

- **Image tag**: a name for one version of a Docker image, such as `latest` or `sha-1a2b3c4`.
- **Index (database)**: a sorted list that makes searching the database fast.
- **Integration test**: a test that uses a real database or service instead of a fake one.
- **Isotonic, sigmoid**: two ways to calibrate a model's confidence scores.

## J

- **joblib**: a Python format for saving objects to a file; loading such a file can run code, so load only files you made.
- **JSON**: a common text format for data, made of names and values.
- **JSON-LD**: JSON data inside a web page that describes the page, such as its publish date.

## K

- **k3s**: a small, light version of Kubernetes.
- **Kubernetes**: a system that runs and watches containers on one or more computers.

## L

- **Label**: the topic given to a story, used to train or to test the classifier.
- **Lease**: a short, timed claim on a job, such as reading one feed, so that two programs never do it at once.
- **Lint**: an automatic check for risky or messy code.
- **Local storage**: space in your browser where a website can keep data on your own computer.
- **Log loss**: a score for how good a model's confidence numbers are; lower is better.
- **Loopback (`127.0.0.1`, `localhost`)**: the address that means "this computer"; other computers cannot reach it.
- **LSTM, GRU**: kinds of neural networks that read things in order, such as a list of stories.

## M

- **Macro-F1**: a score from 0 to 1 that averages how well a classifier does on each topic, so small topics count as much as big ones.
- **Make, Makefile**: a tool that runs named commands, such as `make check`, that are listed in a file called `Makefile`.
- **MCP (Model Context Protocol)**: a standard way for AI agents to find and call tools.
- **Median**: the middle value when you sort a set of measurements.
- **MiB, KiB, MB, kB, GB**: units of size; 1 MiB is 1,048,576 bytes and 1 KiB is 1,024 bytes, while 1 MB is 1,000,000 bytes, 1 kB is 1,000 bytes and 1 GB is 1,000 MB.
- **Migration**: changing the database layout, such as creating collections and indexes, to match the code.
- **Milestone**: a group of roadmap tasks with one goal, such as M2 or RS.
- **MiniBatchKMeans**: a fast way to split items into a chosen number of clusters.
- **MiniLM**: a small language model that turns a sentence into a list of numbers; the classifier uses it.
- **Mock**: a fake stand-in for testing, such as a pretend server with made-up stories.
- **Model**: a program that has learned patterns from examples.
- **Model card**: a short document that says how a model was trained and how well it scored.
- **MongoDB**: the database this project uses.
- **mongodump**: MongoDB's tool for copying a database into backup files.

## N

- **NAS (network-attached storage)**: a disk box on the home network that other computers can save files to.
- **nDCG@5**: a score from 0 to 1 for the top five suggestions that gives more credit to good stories near the top.
- **Neural network**: a model made of layers of simple maths units that learn from examples.
- **Node.js, npm**: Node.js runs JavaScript outside the browser, and npm installs JavaScript packages.

## O

- **OAuth, OpenID Connect**: the standards behind "Sign in with Google".
- **Owner**: the person who runs this project and makes its decisions.

## P

- **p95**: the time within which 95 out of 100 requests finished.
- **Parameter (of a model)**: one number inside a model that training adjusts.
- **PCA, t-SNE**: ways to squeeze many numbers into fewer; t-SNE is mostly used for pictures.
- **Pipeline**: a chain of steps that runs by itself, one after another.
- **PKCE**: a one-time secret that proves the same browser that started a sign-in also finished it.
- **Port**: a numbered door on a computer that one program listens on, such as 8090.
- **Precision@5 (Useful P@5)**: the share of the top five suggestions that a person rated useful.
- **Production**: the real, running copy of the app that readers use.
- **Professional focus**: a reader switch that keeps only sources tagged `ai`, `data-science`, `software` or `technology`.
- **Pull request**: a request on GitHub to add a set of changes to a branch such as `main`.
- **Python**: the programming language of the machine-learning parts and of the web server.

## R

- **Race detector**: a Go tool that finds bugs where two parts of a program change the same data at the same time.
- **Ranker**: the service that puts stories in order for a reader.
- **Rate limit**: a cap on how many requests are allowed in a stretch of time.
- **React**: a JavaScript library for building web pages from small parts called components.
- **Recommender**: the part that suggests stories; it is made of the snapshot build and the ranker.
- **Redirect**: a web answer that says "go to this other address instead".
- **Reinforcement learning**: learning by trial and error from rewards.
- **Release (GitHub)**: a named version on GitHub that can carry files to download.
- **Repository**: a project's folder of code together with its history in git.
- **Requirement (R1–R23)**: one thing V1 must do, listed in section 2 of the roadmap.
- **Revision (`content_rev`)**: a counter on a story that goes up each time its text, its date or its picture link changes.
- **Roadmap**: the plan file [`docs/project/roadmap.md`](project/roadmap.md).
- **robots.txt**: a file on a website that says which pages robots may fetch.
- **Roll back**: to go back to the previous working version.
- **RSS**: the most common format for news feeds.

## S

- **Scheduler**: the part of the collector that wakes up on a timer and starts work.
- **Scraper**: the collector's full-text worker, which fetches story pages.
- **Secret**: a password, key or token that must never be shared or committed.
- **Sentence encoder**: a model, here MiniLM, that turns a sentence into a list of numbers.
- **Service**: a program that runs all the time and answers requests.
- **Session**: the time a reader stays signed in; the server remembers it with a cookie.
- **SHA-256**: a way to make a 64-character fingerprint of a file; if even one byte changes, the fingerprint changes.
- **Silhouette score, WCSS**: two scores for how tight and how separate groups of items are.
- **Snapshot**: a frozen copy of a set of stories that the ranker loads.
- **SSH tunnel**: a safe, encrypted path to a port on another computer.
- **SSRF guard**: a check that stops the collector from being tricked into fetching addresses inside a private network.
- **Staging**: a practice copy of production, used to test a new version before it goes live.
- **stdio**: a program's standard input and output; an AI agent can talk to MCP over it when the agent starts the program itself.
- **SVD**: a maths method that squeezes many word scores into fewer numbers that capture meaning.

## T

- **Taxonomy**: the list of topics and what each one covers, in [`ml/taxonomy.yaml`](../ml/taxonomy.yaml).
- **TensorFlow, Keras**: a library for building and training neural networks, and its easy-to-use layer.
- **Test coverage**: the share of the code that the tests run.
- **Test set**: examples kept apart and used only once, to score a model fairly.
- **TF-IDF**: a way to score the words of a story, so that words that are common in this story but rare in others count most.
- **Token**: a secret string that proves to a service who you are.
- **Topic**: one of the 13 subjects a story can be sorted into, such as `sport`.
- **Two-tower model**: a planned recommender model with one network for readers and one for stories (roadmap C12).
- **Type check**: a check that each value is used as the right kind of thing, such as text or a number.
- **TypeScript**: JavaScript with types; the reader app is written in it.

## U

- **Unique index**: an index that refuses two records with the same value.
- **`unsorted`**: the topic a story gets when the classifier is not sure enough.
- **URL**: a web address, such as `https://example.com/feed.xml`.
- **UTC**: the world's standard time; India time (Asia/Kolkata) is UTC plus 5 hours 30 minutes.
- **UUIDv7**: a kind of unique ID that also records when it was made.
- **uv**: a fast tool that installs Python and Python packages.

## V

- **V1, V2**: V1 is the web version of the product; V2 will add audio briefings and an iPhone app.
- **Vector**: a list of numbers that describes something, such as a story.
- **Vite**: the tool that runs and builds the reader app.
- **Vitest**: the tool that runs the reader app's tests.

## W

- **Webhook**: a web address that another service calls to start an action, such as a deploy.
- **Window (Fresh, Yesterday, Archive)**: the time range that a reader view shows.
- **Worker, thread**: parts of a program that handle requests side by side.
- **Workflow (GitHub Actions)**: a file that tells GitHub which checks and jobs to run.
