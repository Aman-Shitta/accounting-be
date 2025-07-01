import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ai_classify import GLClassifier

if __name__ == "__main__":
    classifier_assistant = GLClassifier(
        api_key="sk-", 
        assistant_id="asst_9SbHYIoj1MnurVtE9UkoAWke",
        vector_store_ids=["vs_6862ae7e625c81918ece89a316d1861b"]
    )

    document_id = "02943fe5-1852-4337-8bb6-882067ce8da7"

    classifier_assistant.classify(document_id)
