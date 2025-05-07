import streamlit as st
import requests
import json
import time
from openai import OpenAI
from pydantic import BaseModel

# Page configuration
st.set_page_config(
    page_title="Lithuanian Market Product Analyzer",
    page_icon="🔍",
    layout="wide"
)

# Title and description
st.title("🔍 Lithuanian Market Product Analyzer")
st.markdown("""
This application analyzes Lithuanian market products based on a technical specification.
It queries the OpenAI API to gather structured product information and evaluates each product.
""")

# Check if API key is configured
if 'openai_api_key' not in st.secrets.get("config", {}):
    st.error("""
    ⚠️ OpenAI API key not found in secrets.

    1. Create a `.streamlit/secrets.toml` file with your OpenAI API key:
    ```
    [config]
    openai_api_key = "your_openai_api_key"
    ```

    2. Restart the application.
    """)
    st.stop()

# Get the API key from secrets
OPENAI_API_KEY = st.secrets["config"]["openai_api_key"]

# Create tabs for different sections
tab1, tab2, tab3 = st.tabs(["Product Search", "Search History", "About"])

with tab1:
    st.header("Search for Products")

    # Product category input
    st.subheader("Product Category/Group")
    product_category = st.text_input(
        "Enter the product category or group:",
        placeholder="Example: Smartphones, Laptops, Vitamins, Sports shoes, Furniture"
    )

    # Product name input (new)
    product_name = st.text_input(
        "Enter the product name:",
        placeholder="Example: iPhone, Vitamin D, Nike Air Max"
    )

    # Technical specification input
    st.subheader("Enter Technical Specification")
    tech_spec = st.text_area(
        "Technical specifications for the product you're looking for:",
        height=200,
        placeholder="Example: Smartphone with at least 6GB RAM, 128GB storage, 6.1 inch OLED display, 5G connectivity, IP68 water resistance"
    )

    # NEW FEATURE: Price Calculation Objective
    st.subheader("Price Calculation Objective")

    price_calculation_options = {
        "none": "No special calculation (standard price)",
        "unit": "Price per unit (e.g., per item)",
        "kg": "Price per kilogram",
        "liter": "Price per liter",
        "package": "Price per package"
    }

    price_calc_objective = st.selectbox(
        "Select how you want prices to be calculated:",
        options=list(price_calculation_options.keys()),
        format_func=lambda x: price_calculation_options[x]
    )

    # Additional input for custom calculation if needed
    custom_calc_unit = None
    if price_calc_objective != "none":
        st.info(f"Products will be evaluated based on {price_calculation_options[price_calc_objective]}")

        if price_calc_objective == "unit":
            custom_calc_unit = st.text_input(
                "Specify unit type (e.g., tablet, pill, piece):",
                placeholder="Leave empty for generic 'unit'"
            )


    # Function to discover URLs for a product based on category and specification
    def discover_product_urls(category, product_name, tech_spec, api_key):
        client = OpenAI(api_key=api_key)

        prompt_initial = f"""
        You need to get information regarding webpages presenting actual product prices. 
        INCLUDE Webpages should be direct seller or price aggregators.
        EXCLUDE news and articles webpages.
        Every item is list must have URL
        Expected result is up to top 20 relevant web pages (URLs). 
         Product to be searched:
         category: {category}
         product name: {product_name}
         product specification: {tech_spec}
         Every item is list must have URL

         Make sure list contains working URLS with product prices
         Check every URL to get product price
        """

        try:
            class URLs(BaseModel):
                urls: list[str]

            response = client.responses.parse(
                model="gpt-4.1",
                tools=[{
                    "type": "web_search_preview",
                    "user_location": {
                        "type": "approximate",
                        "country": "LT",
                        "city": "Vilnius",
                    }
                }],
                temperature=0.2,
                input=prompt_initial,
                text_format=URLs,
            )

            urls = response.output_parsed.urls
            return urls

        except Exception as e:
            st.error(f"Error discovering URLs: {str(e)}")
            return []


    # Step 1: URL Discovery Phase Button
    if st.button("Discover Product URLs", disabled=not (product_category and product_name)):
        if not product_category or not product_name:
            st.warning("Please enter both product category and product name to continue.")
            st.stop()

        with st.spinner(f"Discovering relevant URLs for {product_name} in {product_category} category..."):
            discovered_urls = discover_product_urls(product_category, product_name, tech_spec, OPENAI_API_KEY)

            if discovered_urls:
                st.session_state.discovered_urls = discovered_urls
                st.success(f"Found {len(discovered_urls)} relevant URLs for {product_name}")
            else:
                st.warning("Could not discover any relevant URLs. Try modifying your search criteria.")
                st.session_state.discovered_urls = []

    # Display discovered URLs and allow user to manage them
    if "discovered_urls" in st.session_state and st.session_state.discovered_urls:
        st.subheader("Discovered URLs")
        st.write("Review and manage the discovered URLs before proceeding with price analysis:")

        urls_to_remove = []

        for i, url in enumerate(st.session_state.discovered_urls):
            col1, col2 = st.columns([4, 1])
            with col1:
                st.write(f"{i + 1}. [{url}]({url})")
            with col2:
                if st.checkbox("Include", value=True, key=f"url_{i}"):
                    pass  # Keep URL if checked
                else:
                    urls_to_remove.append(url)

        # Remove unchecked URLs
        for url in urls_to_remove:
            if url in st.session_state.discovered_urls:
                st.session_state.discovered_urls.remove(url)

        # Input for adding new URL
        new_url = st.text_input("Add new URL:", placeholder="Enter a URL (e.g., https://example.lt/product)")
        if st.button("Add URL") and new_url:
            if new_url not in st.session_state.discovered_urls:
                st.session_state.discovered_urls.append(new_url)
                st.success(f"Added {new_url} to the list")
                st.experimental_rerun()
            else:
                st.info(f"{new_url} is already in the list")


    # Function to analyze product prices from a specific URL
    def analyze_product_prices(category, product_name, tech_spec, url, price_calc_objective, api_key):
        client = OpenAI(api_key=api_key)

        prompt = f"""get prices for the following product:
                     category: {category}
                     product name: {product_name}
                     product specification: {tech_spec}
                     from url = {url}

            """
        # JSON format instructions
        prompt += """
        IMPORTANT: Your response MUST be formatted EXACTLY as a valid JSON array of product objects.
        Each product in the array should have the following fields:

        [
          {
            "provider": "Company selling the product",
            "provider_website": "Main website domain (e.g., telia.lt)",
            "provider_url": "Full URL to the specific product page",
            "product_name": "Complete product name with model",
            "product_properties": {
              "key_spec1": "value1",
              "key_spec2": "value2"
            },
            "product_sku": "Any product identifiers (SKU, UPC, model number)",
            "product_price": 299.99,
            "price_per_unit": 9.99,
            "evaluation": "Detailed assessment of how the product meets or fails each technical specification"
          }
        ]

        DO NOT include any explanation, preamble, or additional text - ONLY provide the JSON array.
        """

        try:
            completion = client.chat.completions.create(
                model="gpt-4o-search-preview",
                web_search_options={},
                messages=[
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
            )

            response_text = completion.choices[0].message.content

            # Process the response
            try:
                # Try to parse JSON from response
                import re
                json_match = re.search(r'(\[\s*{.*}\s*\]|\{\s*"products"\s*:\s*\[.*\]\s*\})', response_text, re.DOTALL)

                if json_match:
                    json_str = json_match.group(0)
                    products_data = json.loads(json_str)
                else:
                    products_data = json.loads(response_text)

                # Check if the response is a list or contains a 'products' key
                if isinstance(products_data, dict) and "products" in products_data:
                    products = products_data["products"]
                else:
                    products = products_data

                if isinstance(products, list):
                    return products
                else:
                    return []
            except Exception as e:
                st.warning(f"Could not parse products from URL: {str(e)}")
                return []

        except Exception as e:
            st.error(f"API request failed: {str(e)}")
            return []


    # Function to display the results
    def display_results(all_products, category, product_name, price_calc_objective):
        if not all_products:
            st.error("No products found or error occurred during analysis.")
            return

        # Display the products
        st.subheader(f"Found {len(all_products)} Products for {product_name} in {category} category")

        # Display results in expandable sections
        for i, product in enumerate(all_products):
            product_title = f"{i + 1}. {product.get('product_name', 'Unknown Product')} - €{product.get('product_price', 'N/A')}"

            # Add price calculation to title if available
            if price_calc_objective != "none":
                price_per_key = f"price_per_{price_calc_objective}"
                if price_per_key in product:
                    unit_display = ""
                    if price_calc_objective == "unit" and "unit_type" in product:
                        unit_display = f"/{product['unit_type']}"
                    elif price_calc_objective == "kg":
                        unit_display = "/kg"
                    elif price_calc_objective == "liter":
                        unit_display = "/L"
                    elif price_calc_objective == "package":
                        unit_display = "/pkg"

                    product_title += f" (€{product.get(price_per_key, 'N/A')}{unit_display})"

            with st.expander(product_title):
                col1, col2 = st.columns([1, 2])

                with col1:
                    st.markdown(f"**Provider:** {product.get('provider', 'N/A')}")
                    st.markdown(f"**Website:** {product.get('provider_website', 'N/A')}")
                    if 'provider_url' in product and product['provider_url']:
                        st.markdown(f"**Product Link:** [View Product]({product['provider_url']})")
                    st.markdown(f"**SKU/ID:** {product.get('product_sku', 'N/A')}")
                    st.markdown(f"**Price:** €{product.get('product_price', 'N/A')}")

                    # Display price calculation if available
                    if price_calc_objective != "none":
                        price_per_key = f"price_per_{price_calc_objective}"
                        if price_per_key in product:
                            unit_display = ""
                            if price_calc_objective == "unit" and "unit_type" in product:
                                unit_display = f"/{product['unit_type']}"
                            elif price_calc_objective == "kg":
                                unit_display = "/kg"
                            elif price_calc_objective == "liter":
                                unit_display = "/L"
                            elif price_calc_objective == "package":
                                unit_display = "/pkg"

                            st.markdown(
                                f"**Price per {price_calc_objective.capitalize()}:** €{product.get(price_per_key, 'N/A')}{unit_display}")

                with col2:
                    st.subheader("Product Properties")
                    properties = product.get('product_properties', {})
                    if properties:
                        for key, value in properties.items():
                            st.markdown(f"**{key}:** {value}")
                    else:
                        st.write("No detailed properties available.")

                    st.subheader("Technical Evaluation")
                    evaluation = product.get('evaluation', 'No evaluation available.')
                    st.write(evaluation)

        # Show raw JSON option
        with st.expander("View Raw JSON Response"):
            st.json(all_products)


    # Step 2: Product Price Analysis Button
    if "discovered_urls" in st.session_state and st.session_state.discovered_urls:
        if st.button("Analyze Product Prices", type="primary"):
            with st.spinner(
                    f"Analyzing prices for {product_name} from {len(st.session_state.discovered_urls)} URLs..."):
                all_products = []

                progress_bar = st.progress(0)
                status_text = st.empty()

                active_urls = [url for i, url in enumerate(st.session_state.discovered_urls)
                               if st.session_state.get(f"url_{i}", True)]

                if not active_urls:
                    st.warning("No URLs selected. Please select at least one URL.")
                    st.stop()

                for i, url in enumerate(active_urls):
                    status_text.text(f"Analyzing URL {i + 1}/{len(active_urls)}: {url}")

                    products = analyze_product_prices(
                        product_category,
                        product_name,
                        tech_spec,
                        url,
                        price_calc_objective,
                        OPENAI_API_KEY
                    )

                    if products:
                        all_products.extend(products)

                    # Update progress
                    progress_value = (i + 1) / len(active_urls)
                    progress_bar.progress(progress_value)

                status_text.text("Analysis complete!")

                if all_products:
                    # Save to session state for history
                    if "search_history" not in st.session_state:
                        st.session_state.search_history = []

                    history_entry = {
                        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "category": product_category,
                        "product_name": product_name,
                        "tech_spec": tech_spec,
                        "price_calc_objective": price_calc_objective,
                        "results": all_products
                    }
                    st.session_state.search_history.append(history_entry)

                    # Display the results
                    display_results(all_products, product_category, product_name, price_calc_objective)
                else:
                    st.error("No products found matching your specifications.")


    # Function to display the results
    def display_results(all_products, category, product_name, price_calc_objective):
        if not all_products:
            st.error("No products found or error occurred during analysis.")
            return

        # Display the products
        st.subheader(f"Found {len(all_products)} Products for {product_name} in {category} category")

        # Display results in expandable sections
        for i, product in enumerate(all_products):
            product_title = f"{i + 1}. {product.get('product_name', 'Unknown Product')} - €{product.get('product_price', 'N/A')}"

            # Add price calculation to title if available
            if price_calc_objective != "none":
                price_per_key = f"price_per_{price_calc_objective}"
                if price_per_key in product:
                    unit_display = ""
                    if price_calc_objective == "unit" and "unit_type" in product:
                        unit_display = f"/{product['unit_type']}"
                    elif price_calc_objective == "kg":
                        unit_display = "/kg"
                    elif price_calc_objective == "liter":
                        unit_display = "/L"
                    elif price_calc_objective == "package":
                        unit_display = "/pkg"

                    product_title += f" (€{product.get(price_per_key, 'N/A')}{unit_display})"

            with st.expander(product_title):
                col1, col2 = st.columns([1, 2])

                with col1:
                    st.markdown(f"**Provider:** {product.get('provider', 'N/A')}")
                    st.markdown(f"**Website:** {product.get('provider_website', 'N/A')}")
                    if 'provider_url' in product and product['provider_url']:
                        st.markdown(f"**Product Link:** [View Product]({product['provider_url']})")
                    st.markdown(f"**SKU/ID:** {product.get('product_sku', 'N/A')}")
                    st.markdown(f"**Price:** €{product.get('product_price', 'N/A')}")

                    # Display price calculation if available
                    if price_calc_objective != "none":
                        price_per_key = f"price_per_{price_calc_objective}"
                        if price_per_key in product:
                            unit_display = ""
                            if price_calc_objective == "unit" and "unit_type" in product:
                                unit_display = f"/{product['unit_type']}"
                            elif price_calc_objective == "kg":
                                unit_display = "/kg"
                            elif price_calc_objective == "liter":
                                unit_display = "/L"
                            elif price_calc_objective == "package":
                                unit_display = "/pkg"

                            st.markdown(
                                f"**Price per {price_calc_objective.capitalize()}:** €{product.get(price_per_key, 'N/A')}{unit_display}")

                with col2:
                    st.subheader("Product Properties")
                    properties = product.get('product_properties', {})
                    if properties:
                        for key, value in properties.items():
                            st.markdown(f"**{key}:** {value}")
                    else:
                        st.write("No detailed properties available.")

                    st.subheader("Technical Evaluation")
                    evaluation = product.get('evaluation', 'No evaluation available.')
                    st.write(evaluation)

        # Show raw JSON option
        with st.expander("View Raw JSON Response"):
            st.json(all_products)

with tab2:
    st.header("Search History")

    if "search_history" not in st.session_state or not st.session_state.search_history:
        st.info("No search history yet. Search for products to see your history here.")
    else:
        for i, entry in enumerate(reversed(st.session_state.search_history)):
            # Add category and product name to history entry title
            category_info = f"[{entry.get('category', 'Unknown')}]"
            product_info = f"{entry.get('product_name', 'Unknown Product')}"
            price_calc_info = ""
            if "price_calc_objective" in entry and entry["price_calc_objective"] != "none":
                price_calc_info = f" (Price per {entry['price_calc_objective']})"

            with st.expander(f"{entry['timestamp']} - {category_info} {product_info} {price_calc_info}"):
                st.markdown(f"**Category:** {entry.get('category', 'None')}")
                st.markdown(f"**Product:** {entry.get('product_name', 'None')}")
                st.markdown(f"**Search Query:**\n{entry['tech_spec']}")

                # Show price calculation objective if available
                if "price_calc_objective" in entry and entry["price_calc_objective"] != "none":
                    st.markdown(f"**Price Calculation:** Price per {entry['price_calc_objective']}")

                st.markdown(f"**Results:** {len(entry['results'])} products found")

                # Display results again
                for j, product in enumerate(entry['results']):
                    # Basic product info
                    product_info = f"**{j + 1}. {product.get('product_name', 'Unknown Product')}** - €{product.get('product_price', 'N/A')}"

                    # Add price calculation if available
                    if "price_calc_objective" in entry and entry["price_calc_objective"] != "none":
                        price_per_key = f"price_per_{entry['price_calc_objective']}"
                        if price_per_key in product:
                            unit_display = ""
                            if entry["price_calc_objective"] == "unit" and "unit_type" in product:
                                unit_display = f"/{product['unit_type']}"
                            elif entry["price_calc_objective"] == "kg":
                                unit_display = "/kg"
                            elif entry["price_calc_objective"] == "liter":
                                unit_display = "/L"
                            elif entry["price_calc_objective"] == "package":
                                unit_display = "/pkg"

                            product_info += f" (€{product.get(price_per_key, 'N/A')}{unit_display})"

                    st.markdown(product_info)
                    st.markdown(
                        f"Provider: {product.get('provider', 'N/A')} | [View Product]({product.get('provider_url', '#')})")

with tab3:
    st.header("About This Application")

    st.markdown("""
    ## Lithuanian Market Product Analyzer

    This application helps you find and compare products available in the Lithuanian market
    based on technical specifications you provide. It leverages the OpenAI API to search
    for and analyze products from various Lithuanian retailers.

    ### How to Use

    1. Enter the product category or group (e.g., Smartphones, Vitamins, Sports equipment)
    2. Enter the product name (e.g., iPhone, Vitamin D, Nike Air Max)
    3. Enter the technical specifications for the product you're looking for
    4. Select a price calculation objective if you want to compare prices on a specific basis
    5. Click "Discover Product URLs" to find relevant product pages
    6. Review, add, or remove URLs as needed
    7. Click "Analyze Product Prices" to get detailed information from the selected URLs
    8. Review the results, which show:
       - Product details and standard pricing
       - Price calculations based on your selected objective (per kg, per unit, etc.)
       - Technical specifications evaluation
       - Links to product pages

    ### Tips for Best Results

    - Be specific with your product category and name
    - Include both must-have and nice-to-have features in your specifications
    - Specify brand preferences if you have any
    - Include price range if relevant
    - Use the price calculation objectives for better comparison between products (e.g., price per kg for groceries)
    - Check the discovered URLs before analysis to ensure they're relevant

    ### Technical Details

    This application uses:
    - Streamlit for the web interface
    - OpenAI API with GPT-4o Search for intelligent market research
    - Two-step search approach:
      1. First discovers relevant product URLs
      2. Then analyzes each URL for detailed product information
    - JSON for structured data handling
    - Customizable URL selection for targeted searches
    - Specialized price calculations for better product comparison

    ### Privacy Note

    Your search queries and technical specifications are sent to the OpenAI API
    to generate results. No personal information is stored or shared beyond what is 
    necessary for the application to function.
    """)

# Footer
st.markdown("---")
st.markdown("© 2025 Lithuanian Market Product Analyzer | Powered by OpenAI API")