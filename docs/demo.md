# MoveOn — AI Live Demo Guide

**INFO 490**

**Demo Date:** Thursday, November 12, 2026
**Environment:** Local Django Application

---

## 1. Project Overview

MoveOn is an AI-assisted resale marketplace that helps students sell their belongings before moving out and helps buyers find affordable secondhand items.

We integrate AI into the marketplace to simplify listing creation, improve product discovery, and recommend combinations of products.

### Our AI Features

| Feature                   | AI Model / Method                           | Purpose                                                          |
| ------------------------- | ------------------------------------------- | ---------------------------------------------------------------- |
| AI Listing Photo Autofill | Gemini 3.5 Flash-Lite                       | Generates listing details from uploaded photos                   |
| AI Bundle Recommendations | Gemini 3.6 Flash                            | Recommends product bundles based on buyer preferences            |
| AI-Assisted Pricing       | Sentence Transformers + statistical pricing | Matches item types and recommends evidence-based starting prices |
| Natural-Language Search   | Llama 3.2 3B Instruct                       | Helps buyers find items using everyday language                  |

**Note:** Price guides use historical observations or current MoveOn asking prices when enough relevant local listings exist. Sentence Transformers helps identify item types; it does not generate prices.

---

# 2. Live Demo

### Objectives

- Demonstrate the application running locally.
- Show at least two successful AI cases.
- Demonstrate at least one AI failure or limitation.

## Successful Case 1: AI Listing Photo Autofill + Listing Price Recommendation

**Scenario:** A student wants to sell a chair without manually writing a product description.

**Demo Steps:**

1. Navigate to **Seller → Create Listing**.
2. Upload a photo of a chair.
3. Click **Fill Details from Photos**.
4. Show the AI-generated title, description, item type, and condition.
5. Explain that sellers can review and edit the suggestions.

**How AI Adds Value:**

- Saves time when creating listings.
- Automatically identifies visible product details.
- Reduces manual data entry.



---

## Successful Case 2: AI-Powered Bundle Recommendations

**Scenario:** A student wants to furnish a living room without searching for each item separately.

**Demo Steps:**

1. Navigate to **Buyer → Bundle Builder**.
2. Select **Living Room**.
3. Choose categories such as sofa, rug, lamp, and coffee table.
4. Generate AI bundle recommendations.
5. Show the **Budget, Best Value, and Premium** options.

**How AI Adds Value:**

- Helps buyers find complementary items.
- Reduces the effort needed to furnish an entire room.
- Recommends different product combinations based on buyer preferences.



---

## Failure / Limitation Case: AI Natural-Language Search

**Scenario:** A buyer searches by describing what an item does rather than naming the product.

**Example Query:**

> "I need something to heat up food quickly."

**Expected Result:**

- AI understands that the buyer is looking for a microwave.
- Relevant microwave listings are displayed.

**Actual Result:**

- Llama successfully loaded, but search took several minutes on my Windows laptop.
- Some searches timed out or displayed unrelated fallback listings.
- The same feature worked successfully on my teammate's laptop.

### Limitation 1: Hardware-Dependent AI Performance

**What we observed:**

- The same Llama model performed differently across our laptops.
- On my Windows laptop (16 GB RAM, CPU-only), inference was extremely slow or timed out.
- On my teammate's laptop, the feature worked successfully.

**Why this happens:**

- We identified a possible hardware compatibility issue.
- My CPU does not natively support `bfloat16`, the numerical format used by the model.
- This likely makes AI processing slower, even though the model and code are the same.
- Switching numerical formats may improve compatibility but could require more memory.

**How we would improve it:**

- Optimize inference settings for different hardware configurations.
- Reduce unnecessary processing and model input size.
- Host Llama on a dedicated GPU-enabled server for more consistent performance.



### Limitation 2: Search Relevance

**What we observed:**

- Some searches displayed unrelated fallback products.
- Our search validation can reject relevant items when the query and listing use different words.

**Why this happens:**

- Llama interprets natural language, but our application also applies word-based relevance checks.
- For example, "heat up food" and "microwave" have similar meanings but do not share exact words.
- This can cause valid recommendations to be rejected.

**How we would improve it:**

- Use semantic similarity rather than relying mainly on matching words.
- Reduce the number of listings sent to Llama through semantic candidate selection.
- Test search accuracy across different types of queries.



---

# 3. Technical Explanation

## A. Where Does AI Enter MoveOn?

AI supports three main stages of the marketplace experience.

**1. Listing Creation**

- Sellers upload product photos or enter descriptions.
- AI helps identify products and suggest listing details.
- Historical observations and current active listings can provide starting-price references.

**2. Product Discovery**

- Buyers describe what they're looking for using natural language.
- AI interprets the query and attempts to rank relevant listings.

**3. Bundle Creation**

- Buyers select a room and desired products.
- AI recommends combinations of available marketplace items.

**Key Point:** AI assists users in making decisions, but sellers and buyers maintain control over their final choices.

---

## B. Which Models Do We Use?

### 1. Gemini — AI Listing Photo Autofill

**Model:** Gemini 3.5 Flash-Lite

- Analyzes uploaded product photos.
- Identifies visible characteristics.
- Generates suggested titles, descriptions, item types, and conditions.
- Allows sellers to review and edit the results.

**Why this model?**

Gemini can understand images and generate text, making it useful for automating listing creation.

### 2. Gemini — AI Bundle Builder

**Model:** Gemini 3.6 Flash

- Receives the buyer's selected space and product categories.
- Evaluates available listings.
- Recommends Budget, Best Value, and Premium combinations.

**Why this model?**

Gemini can consider multiple products and preferences when suggesting useful combinations.

### 3. Sentence Transformers — AI-Assisted Pricing

**Model:** `all-MiniLM-L6-v2`

- Converts product descriptions into numerical representations called *embeddings*.
- Compares them with known item types to identify similar products.
- Helps sellers select the correct category and item type.
- Uses historical observations or current active asking prices to calculate a starting-price reference.

**Why this model?**

Sentence Transformers recognizes similarities in meaning, even when descriptions use different words.

**Important:** The price reference is a median of comparable prices, not a price generated directly by AI. Current listings are asking prices, not completed sales.

### 4. Llama — Natural-Language Search

**Model:** Meta Llama 3.2 3B Instruct

- Receives a buyer's search query.
- Reviews candidate listings from the marketplace.
- Identifies potentially relevant products.
- Returns listing IDs that Django validates before displaying.

**Why this model?**

Llama can interpret conversational language and help buyers find products without knowing the exact product name.

---

## C. How Are AI Inputs Processed?

Our general AI workflow is:

**User Input → Django Backend → Data Preparation → AI Model → Output Validation → User Interface**

| Step | Explanation | Description |
|---|---|---|
| **1. User Input** | A user uploads a photo, enters a search query, or selects bundle preferences. | AI processing begins when a user requests assistance through the app. For example, a seller uploads a product photo, or a buyer describes what they want to purchase. |
| **2. Django Backend** | The application receives and validates the request. | Django acts as the connection between the user interface and the AI models. It checks the submitted information and determines which AI feature should handle the request. |
| **3. Data Preparation** | Relevant images, text, or available listings are prepared for AI analysis. | MoveOn organizes inputs into a format the model can understand. For example, it resizes uploaded images or retrieves relevant product information from the database before sending it to AI. |
| **4. AI Model** | Gemini, Sentence Transformers, or Llama processes the information. | The selected model analyzes the prepared input and generates suggestions. Depending on the feature, this could be a product description, a list of matching items, or recommended product bundles. |
| **5. Output Validation** | MoveOn checks that recommendations are valid and reference actual items. | Django checks the AI-generated results against the application's rules and database. It filters out invalid suggestions, such as nonexistent listing IDs, unsupported item types, or recommendations that do not meet eligibility requirements. |
| **6. User Interface** | Recommendations are displayed for users to review. | Validated results are returned to the website and presented in a user-friendly format. Sellers and buyers can review the recommendations before taking further action. |

### How Does MoveOn Validate AI Outputs?

MoveOn uses **server-side validation**, meaning AI-generated suggestions are checked by Django before being presented or used in the application.

- **Photo Autofill:** Ensures AI-generated item types belong to existing categories and validates suggested information before filling the listing form.
- **Natural-Language Search:** Checks that Llama returns valid listing IDs, removes duplicates, verifies listing eligibility, and applies additional relevance checks.
- **Bundle Recommendations:** Uses eligible marketplace inventory and validates proposed combinations against application rules.
- **AI-Assisted Pricing:** Uses historical observations or active MoveOn asking prices and applies minimum-price safeguards rather than relying on AI-generated prices.

**Why is validation important?**

AI can occasionally generate inaccurate information or recommend products that do not exist. By validating model outputs against our database and business rules, MoveOn reduces these risks and ensures users retain control over their final decisions.

## D. What Are the Current Limitations?

| Limitation                | Explanation                                                                           |
| ------------------------- | ------------------------------------------------------------------------------------- |
| Hardware compatibility    | Llama runs much slower on CPUs without efficient support for its numerical format.    |
| Slow AI inference         | Llama can take several minutes on CPU-only computers.                                 |
| Search relevance          | Word-based checks can reject relevant products described using different terminology. |
| Inconsistent AI responses | The same photo or query can occasionally produce different results.                   |
| Historical pricing data   | Our 2023 US-wide data may not reflect current local student resale prices.            |
| External API dependency   | Gemini features depend on API availability and usage limits.                          |

---

## E. How Would We Improve MoveOn Before Deployment?

### 1. Improve AI Performance

- Host Llama on GPU-enabled infrastructure.
- Optimize model settings and processing speed.
- Reduce unnecessary data sent to AI models.

### 2. Improve Search Accuracy

- Use Sentence Transformers to identify semantically relevant listings.
- Let Llama rank a smaller set of promising results.
- Improve relevance validation and test more diverse queries.

### 3. Improve Reliability

- Add better error handling and response validation.
- Monitor AI response times and failures.
- Allow users to correct inaccurate recommendations.

### 4. Improve Pricing Accuracy

- Collect more recent, verified local resale data.
- Evaluate recommendations against real completed transactions.
- Continue giving sellers control over final prices.

---

# 4. Closing Summary

MoveOn demonstrates how AI can improve the student resale experience by simplifying listing creation, helping buyers discover products, and recommending useful product bundles.

Our application combines:

- **Gemini** for image analysis and bundle recommendations.
- **Sentence Transformers** for semantic product matching.
- **Llama 3.2 3B** for natural-language search.
- **Statistical pricing methods** for evidence-based starting-price recommendations.

Our successful demonstrations show that AI is integrated into the actual Django application, from user input through model inference to validated results.

We also identified real limitations involving hardware compatibility, inference speed, and search relevance.

**Key Takeaway:** Building an AI-powered application involves more than integrating models. We must also ensure that the system is accurate, reliable, and efficient enough for real users.


# 5. Model Rationale Details

## 5.1 AI Listing Photo Autofill — Gemini 3.5 Flash-Lite

**Model:** Google Gemini 3.5 Flash-Lite

**Approach:** Multimodal AI (Image Understanding + Text Generation)

**Rationale:**

We selected Gemini because it is a **multimodal AI model**, meaning it can understand images and generate text. When sellers upload product photos, Gemini identifies visible characteristics and suggests listing details such as the title, description, item type, and condition. We use the Flash-Lite variant because it is designed for efficient, lower-cost processing, making it suitable for frequent listing requests. This reduces manual data entry while allowing sellers to review and correct AI-generated information.

**Limitations:**
- Image recognition may be inaccurate when photos are blurry, poorly lit, or ambiguous.
- AI cannot reliably determine hidden defects or actual product functionality from a photo.
- Performance depends on external API availability.

---

## 5.2 AI Bundle Recommendations — Gemini 3.6 Flash

**Model:** Google Gemini 3.6 Flash

**Approach:** Generative AI + Context-Aware Recommendations

**Rationale:**

We selected Gemini for bundle recommendations because it can **evaluate multiple products and buyer preferences together** rather than treating each listing independently. MoveOn provides the model with the buyer's selected room, desired categories, and available marketplace inventory. Gemini then recommends combinations of complementary products across Budget, Best Value, and Premium options. Its ability to reason about product relationships makes it useful for helping buyers furnish entire spaces instead of searching for individual items.

**Limitations:**
- Recommended combinations may not always reflect personal taste or practical compatibility.
- AI outputs can vary across requests.
- Recommendations must be validated against actual inventory and seller constraints.
- Gemini does not independently guarantee product availability or seller approval.

---

## 5.3 AI-Assisted Listing Price Suggestions — Sentence Transformers

**Model:** `all-MiniLM-L6-v2`

**Approach:** Zero-Shot Semantic Matching + Comparable-Price Medians

**Rationale:**

We use **zero-shot semantic matching** through a pretrained Sentence Transformers model to identify relevant product types without training a custom classification model. The model converts product descriptions into numerical representations called *embeddings* and uses **cosine similarity** to compare their meanings, even when different words are used. For example, "wooden workstation for studying" may be matched to "desk."

Once the seller confirms the item type, MoveOn calculates a median from comparable historical MerRec observations or active MoveOn asking prices. When a historical guide exists, at least three distinct local sellers are needed before the live guide replaces it. A single live listing can supply a clearly warned provisional reference when the historical sample has no guide. We selected the median because it is less affected by unusually high or low prices than the average; our regression comparison evaluated the historical dataset only.

This combination provides AI-based product matching while keeping price references traceable to their source rather than AI-generated estimates.

**Limitations:**
- Semantic similarity does not guarantee correct product classification.
- Our 2023 US-wide pricing data may not reflect current local resale values.
- Limited comparable observations reduce pricing reliability.
- Historical observed prices are not necessarily verified completed-sale prices.
- Current MoveOn listings provide asking prices, not verified sale prices; broad item types can group unlike products.

---

## 5.4 Move-Out Deadline Pricing — Power Curve

**Method:** Bounded Power Curve

**Approach:** Deterministic Mathematical Pricing

**Rationale:**

We chose a **power curve over an exponential curve** because it provides a simple, predictable way to reduce prices while ensuring they reach the seller's chosen minimum at the move-out deadline. Unlike a standard exponential decay curve, which approaches a minimum without reaching it exactly, our power curve has clearly defined starting and ending prices.

The exponent (**γ**) controls how quickly prices decrease:
- **γ < 1:** Larger discounts occur earlier in the selling period.
- **γ = 1:** Prices decrease at a constant, linear rate.
- **γ > 1:** Larger discounts are delayed until closer to move-out.

We selected **γ = 2** for the normal strategy because it allows sellers to preserve their asking price early while accelerating reductions as the deadline approaches. Our urgent strategy uses **γ = 1.2** to recommend earlier discounts when sellers prioritize selling quickly.

These values are initial design assumptions rather than statistically optimized parameters. We would refine them using real transaction data to balance seller returns and the likelihood of selling before moving out.

**Limitations:**
- The curve assumes urgency increases as the move-out date approaches.
- It does not currently account for real-time buyer demand.
- The exponent values have not been calibrated using actual MoveOn sales.
- Suggested reductions require seller approval; the curve does not guarantee a sale.

**Important:** This is a mathematical pricing algorithm, not a machine-learning model.

---

## 5.5 Natural-Language Search — Llama 3.2 3B Instruct

**Model:** Meta Llama 3.2 3B Instruct

**Approach:** Large Language Model (LLM) + Contextual Product Ranking

**Rationale:**

We selected Llama because it can **interpret conversational language and understand buyer intent**, allowing users to search based on what they need rather than exact product names. For example, a buyer searching for "something to heat up food quickly" should be able to discover microwave listings without explicitly mentioning "microwave."

We chose the 3B Instruct variant as a compromise between language understanding and computational requirements. Its relatively smaller size makes local experimentation more practical than using much larger language models, while preserving the ability to process natural-language instructions.

The model receives a buyer's query and candidate listings, then returns potentially relevant listing IDs. Django validates these IDs before displaying recommendations.

**Limitations:**
- Local inference can be extremely slow on CPU-only hardware.
- Differences in CPU architecture and numerical-format support can cause significant performance differences between laptops.
- Word-based relevance checks may reject semantically correct matches.
- The model may produce irrelevant recommendations or fail to finish before a timeout.

**Future improvements:**
- Use semantic embeddings to retrieve promising listings before Llama ranking.
- Reduce model input size and optimize inference settings.
- Deploy inference on GPU-enabled infrastructure.
- Evaluate search quality across diverse queries and product categories.

---

## 5.6 Summary of Model Selection

| Feature | Model / Method | Why We Chose It |
|---|---|---|
| **Listing Photo Autofill** | Gemini 3.5 Flash-Lite | Understands product images and generates listing descriptions efficiently. |
| **AI Bundle Builder** | Gemini 3.6 Flash | Evaluates multiple listings and buyer preferences to recommend complementary products. |
| **Listing Price Suggestions** | Sentence Transformers + Comparable-Price Median | Combines zero-shot semantic product matching with source-labeled historical or current asking-price references. |
| **Move-Out Deadline Pricing** | Power Curve (γ = 2 / 1.2) | Provides predictable, progressively larger markdown recommendations while respecting seller-approved minimums. |
| **Natural-Language Search** | Llama 3.2 3B Instruct | Interprets conversational buyer intent and ranks relevant product listings. |

**Overall Rationale:**

Rather than relying on a single AI model for every task, MoveOn uses **different methods based on the problem being solved**. We use generative AI for image understanding and product recommendations, semantic embeddings for identifying similar products, statistical methods for historical price benchmarks, and mathematical algorithms for deadline-based pricing.

This approach allows us to use AI where it adds meaningful value while keeping financial decisions transparent, explainable, and under seller control.
