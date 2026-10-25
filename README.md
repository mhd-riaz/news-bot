# news-bot

News collection, topic classification, and **AFTERLINE**, a content-based news archive recommender with a Stories-inspired reader.

- [Recommendation setup, training, evaluation and architecture](collector/docs/recommender.md)
- [Verified results and limitations](collector/docs/recommender-results.md)
- [Client and architecture review briefing](collector/docs/recommender-client-review.md)
- [Collector and classification project](collector/readme.md)

The recommender compares TF-IDF, SVD and locally trained TensorFlow/Keras article representations. Interests are explicit and browser-local—not preferences learned from historical users. Original MongoDB articles are never modified by the recommendation workflow or read-only reader.
