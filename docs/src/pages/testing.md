---
title: Testing
---

# Testing Individual Operators

** Example Commands **

```
nose2 operators.test_detect_text_in_image.Test
nose2 operators.test_detect_lang_of_text.Test
nose2


nose2 core.store.test_es


# testing a single function
nose2 feature.index.test_index.TestIndex.testRepresentImage
```