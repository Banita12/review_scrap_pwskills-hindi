from flask import Flask, render_template, request, jsonify
from flask_cors import CORS, cross_origin # CORS is imported but not used in this specific example
import requests
from bs4 import BeautifulSoup as bs
from urllib.request import urlopen as uReq
import logging
import os # Import os module to handle file paths
import pymongo

# Configure logging to capture more details, including line numbers and time
logging.basicConfig(filename="scrapper.log", level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s - Line:%(lineno)d')

app = Flask(__name__)

# Route for the homepage, handles GET requests
@app.route("/", methods=['GET'])
def homepage():
    logging.info("Accessed homepage.")
    return render_template("index.html")

# Route to handle review scraping, supports POST and GET
@app.route("/review", methods=['POST', 'GET'])
def index():
    if request.method == 'POST':
        try:
            searchString = request.form['content'].replace(" ", "")
            logging.info(f"Search string received: {searchString}")

            # Construct Flipkart search URL
            flipkart_url = "https://www.flipkart.com/search?q=" + searchString
            logging.info(f"Attempting to open Flipkart search URL: {flipkart_url}")

            # Open the URL and read the page content
            uClient = uReq(flipkart_url)
            flipkartPage = uClient.read()
            uClient.close()
            logging.info("Flipkart search page successfully fetched.")

            # Parse the HTML content of the search page
            flipkart_html = bs(flipkartPage, "html.parser")

            # --- IMPORTANT: UPDATE THESE SELECTORS ---
            # Flipkart's HTML structure changes frequently.
            # You need to inspect the current HTML of Flipkart search results
            # and product pages using your browser's developer tools (F12).

            # Example: Finding product boxes on the search results page
            # Look for a common div that contains individual product listings.
            # This class "_1AtVbE col-12-12" is very likely outdated.
            # You'll need to find the current class for product containers.
            bigboxes = flipkart_html.findAll("div", {"class": "cPHDOP col-12-12"})
            if not bigboxes:
                logging.warning("No product big boxes found with the current selector '_1AtVbE col-12-12'. Check Flipkart HTML.")
                raise Exception("Could not find product listings on Flipkart search page. HTML structure might have changed.")

            # Remove initial non-product divs (e.g., ads, filters)
            # This assumes the first 3 divs are always non-product related.
            # This might also need adjustment based on current Flipkart layout.
            if len(bigboxes) > 3:
                del bigboxes[0:3]
            else:
                logging.warning("Less than 4 big boxes found. 'del bigboxes[0:3]' might remove all products or cause issues.")
                # Handle case where there are fewer than 3 elements or no elements after deletion
                if not bigboxes:
                    raise Exception("No product boxes left after initial deletion. Check search page structure.")


            # Select the first product box to get its link
            box = bigboxes[0]
            # Extract the product link. This path (div.div.div.a['href']) is also highly sensitive to changes.
            # Look for the <a> tag that wraps the product and contains the href.
            productLink = "https://www.flipkart.com" + box.div.div.div.a['href']
            logging.info(f"Found product link: {productLink}")

            # Fetch the product's individual page
            prodRes = requests.get(productLink)
            prodRes.encoding='utf-8'
            prod_html = bs(prodRes.text, "html.parser")
            logging.info("Product page successfully fetched and parsed.")

            # Find all comment boxes on the product page
            # This class "col EPCmJX Ma1fCG" is also very likely outdated for review containers.
            commentboxes = prod_html.find_all('div', {'class': "col EPCmJX Ma1fCG"})
            if not commentboxes:
                logging.warning("No comment boxes found with the current selector 'col EPCmJX Ma1fCG'. Check product review page HTML.")
                # Attempt to find "All reviews" link and scrape from there if main page has no reviews
                all_reviews_link_tag = prod_html.find('a', {'class': '_1LKTO3'}) # Common class for "All reviews" button
                if all_reviews_link_tag and 'href' in all_reviews_link_tag.attrs:
                    all_reviews_url = "https://www.flipkart.com" + all_reviews_link_tag['href']
                    logging.info(f"Found 'All Reviews' link: {all_reviews_url}. Attempting to scrape from there.")
                    all_reviews_res = requests.get(all_reviews_url)
                    all_reviews_res.encoding = 'utf-8'
                    all_reviews_html = bs(all_reviews_res.text, "html.parser")
                    commentboxes = all_reviews_html.find_all('div', {'class': "col EPCmJX Ma1fCG"}) # Try same class again
                    if not commentboxes:
                        logging.warning("Still no comment boxes found on 'All Reviews' page. Selectors are definitely outdated.")
                        raise Exception("No reviews found for this product. HTML structure might have changed.")
                else:
                    raise Exception("No reviews found for this product and no 'All Reviews' link. HTML structure might have changed.")


            # Define filename for CSV, ensure it's in a 'reviews_data' directory
            output_dir = 'reviews_data'
            os.makedirs(output_dir, exist_ok=True) # Create directory if it doesn't exist
            filename = os.path.join(output_dir, f"{searchString}.csv")

            # Open CSV file for writing (use 'with' statement for automatic closing)
            with open(filename, "w", encoding='utf-8', newline='') as fw:
                headers = "Product, Customer Name, Rating, Heading, Comment \n"
                fw.write(headers)
                reviews = []

                for i, commentbox in enumerate(commentboxes):
                    try:
                        # Name selector: '_2NsDsF AwS1CA' is likely outdated
                        name = commentbox.div.div.find('p', {'class': '_2NsDsF AwS1CA'})
                        name = name.text if name else 'No Name'
                    except Exception as e:
                        logging.error(f"Error extracting name for commentbox {i}: {e}")
                        name = 'No Name'

                    try:
                        # Rating selector: div.div.div.div.text is very fragile
                        # Look for the div containing the rating, often has a class like 'XQDdHH Ga3i8K'
                        rating_tag = commentbox.find('div', {'class': 'XQDdHH Ga3i8K'}) # Example class for rating (e.g., 4.5 star)
                        rating = rating_tag.text if rating_tag else 'No Rating'
                    except Exception as e:
                        logging.error(f"Error extracting rating for commentbox {i}: {e}")
                        rating = 'No Rating'

                    try:
                        # Comment Heading selector: div.div.div.p.text is also fragile
                        commentHead_tag = commentbox.find('p', {'class': 'z9E0IG'}) # Example class for review title
                        commentHead = commentHead_tag.text if commentHead_tag else 'No Comment Heading'
                    except Exception as e:
                        logging.error(f"Error extracting comment heading for commentbox {i}: {e}")
                        commentHead = 'No Comment Heading'

                    try:
                        # Comment text selector: find_all('div', {'class': ''}) is problematic
                        # An empty class name is highly unreliable. Look for the specific class of the comment text.
                        # Example: '_1mRjO5' or similar for the actual review text
                        custComment_tag = commentbox.find('div', {'class': 'row'}) # Example class for review text
                        custComment = custComment_tag.text if custComment_tag else 'No Comment'
                    except Exception as e:
                        logging.error(f"Error extracting customer comment for commentbox {i}: {e}")
                        custComment = 'No Comment'

                    mydict = {
                        "Product": searchString,
                        "Name": name,
                        "Rating": rating,
                        "CommentHead": commentHead,
                        "Comment": custComment
                    }
                    reviews.append(mydict)
                    fw.write(f"{searchString},{name},{rating},{commentHead},{custComment}\n") # Write to CSV

                logging.info(f"Scraping completed. Total reviews collected: {len(reviews)}")
                # logging.info("Log my final result: {}".format(reviews)) # This can be very verbose for many reviews

                # Return all reviews, not excluding the last one
                return render_template('result.html', reviews=reviews)

        except Exception as e:
            logging.error(f"An error occurred during scraping: {e}", exc_info=True) # Log full traceback
            return render_template('result.html', reviews=[], error_message=f"Something went wrong: {e}. Please check the logs for details.")

    else: # Handles GET request for /review (e.g., if someone types /review directly)
        logging.info("Accessed /review with GET request, redirecting to homepage.")
        return render_template('index.html')


if __name__ == "__main__":
    app.run(debug=True, port=5000)
