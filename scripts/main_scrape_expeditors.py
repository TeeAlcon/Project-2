import asyncio
from pathlib import Path
import os
import pandas as pd
from scripts.utils.combine_scrape_pdf import combine_saved_pdfs 
from scripts.utils.login_interface import get_credentials
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError


URL = "https://go2expo.expeditors.com/dashboard"


EDGE_USER_DATA_DIR = (
    Path(os.environ["LOCALAPPDATA"])
    / "Microsoft"
    / "Edge"
    / "User Data"
)

async def login(page, username, password):
    await page.goto(URL)

    await page.wait_for_load_state("domcontentloaded")

    email_box = page.get_by_role("textbox", name="Email")
    password_box = page.get_by_role("textbox", name="Password")

    await email_box.wait_for(timeout=10000)
    await password_box.wait_for(timeout=10000)

    await email_box.fill(username)
    await password_box.fill(password)

    await page.get_by_role("button", name="Sign In").click()

async def determine_auth_state(page):
    try:
        await page.wait_for_load_state("domcontentloaded")

        await asyncio.wait_for(
            asyncio.gather(
                page.locator("#track-your-shipment-widget").wait_for(
                    state="visible"
                )
            ),
            timeout=5,
        )

        return "logged_in"

    except:
        return "login_required"
    
async def fail_log_in(page) -> bool:
    try:
        await page.get_by_text(
            "Wrong email or password."
        ).wait_for(state="visible", timeout=3000)

        return True

    except PlaywrightTimeoutError:
        return False

async def save_pdfs_from_view_click(page, output_dir: Path, quiet_time: float = 1.0):
    output_dir.mkdir(parents=True, exist_ok=True)

    pdf_responses = []
    new_tabs = []
    tab_queue = asyncio.Queue()

    # Capture response
    def on_response(response):
        if "application/pdf" in response.headers.get("content-type", "").lower():
            pdf_responses.append(response)

    # See blob tab only. Do nothing with it 
    def on_page(new_page):
        tab_queue.put_nowait(new_page)

    page.context.on("response", on_response)
    page.context.on("page", on_page)

    try:
        await page.get_by_role("button", name="View").click()

        # Must see at least one PDF tab.
        try:
            first_tab = await asyncio.wait_for(tab_queue.get(), timeout=30)
            new_tabs.append(first_tab)
        except asyncio.TimeoutError:
            return []

        # Then collect tabs until no new tab appears briefly
        while True:
            try:
                tab = await asyncio.wait_for(tab_queue.get(), timeout=1)
                new_tabs.append(tab)
            except asyncio.TimeoutError:
                break

        # give PDF responses time to finish arriving
        await asyncio.sleep(quiet_time)

    finally:
        page.context.remove_listener("response", on_response)
        page.context.remove_listener("page", on_page)

    saved = []

    for i, response in enumerate(pdf_responses, start=1):
        try:
            # Make sure the network response has fully completed
            body = await response.body()

            # Validate PDF
            if not body.startswith(b"%PDF"):
                continue
            
            if b"%%EOF" not in body[-4096:]:
                continue

            path = output_dir / f"pdf_{i}.pdf"
            path.write_bytes(body)
            saved.append(path)

        except Exception as e:
            print(f"Could not save PDF response {i}")

    for tab in new_tabs:
        await tab.close()

    return saved


async def is_itn_valid(page) -> bool:
    invalid_indicators = [page.get_by_text("Track again", exact=False)]
    for locator in invalid_indicators:
        try:
            await locator.first.wait_for(state="visible", timeout=3000)
            return False  
        except PlaywrightTimeoutError:
            pass
    return True  


async def playwright_automation(page, itns):
    await asyncio.to_thread(input, "\nEnsure you are logged in and press Enter...")
    
    #await page.get_by_role("button", name="dropdown trigger").click()
    #await page.get_by_text("Declarations", exact=True).click()

    for itn in itns:
        await page.locator("#actionboxInputTrack").get_by_role("textbox").fill(itn)
        await page.locator("#track-your-shipment-widget #expo-shared-button").click()

        is_valid = await is_itn_valid(page)
        if not is_valid:
            print(f"ITN {itn} not found")
            continue 

        await page.get_by_role("link", name="Documents").click()

        #checkboxes = page.locator("tr .checkbox-field p-tablecheckbox .p-checkbox .p-checkbox-input")
        #await checkboxes.first.wait_for(state="visible")
        # Click all checkboxes            
        #count = await checkboxes.count()
        #for i in range(count):
        #    cb = checkboxes.nth(i)
        #    if await cb.is_enabled():
        #        await cb.click()

        await page.get_by_role("row", name="Document Type Arrow Group").get_by_role("checkbox").click()

        out = Path.cwd() / "test" / itn
        saved_pdfs = await save_pdfs_from_view_click(page, out)

        if saved_pdfs:
            combine_saved_pdfs(saved_pdfs, out / f"{itn}.pdf")

def read_itns_from_csv():
    csv_path = input("Paste the full path to the CSV file: ").strip().strip('"')
    csv_path = Path(csv_path)

    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    df = pd.read_csv(csv_path, dtype=str)

    itn_column = None

    for column in df.columns:
        if str(column).strip().lower() == "itn":
            itn_column = column
            break

    if itn_column is None:
        raise ValueError("Could not find an ITN column. ")
    
    itns = df[itn_column].dropna().astype(str).str.strip().tolist()

    return [itn for itn in itns if itn]

async def run_playwright(itns):
        async with async_playwright() as p:
        #context = await p.chromium.launch_persistent_context(
            user_data_dir=EDGE_USER_DATA_DIR,
            channel="msedge",
            headless=False,
            slow_mo=100,
            accept_downloads=True,
            no_viewport=False,
            permissions=["clipboard-read", "clipboard-write"],
            #ignore_https_errors=True,)   # run launch_persistent_context to not log in
        
        browser = await p.chromium.launch(
            channel="msedge",
            headless=False # run headless=True if user don't want browser-popup
        )
        context = await browser.new_context(
            accept_downloads=True,
            permissions=["clipboard-read", "clipboard-write"],
        )
        try:
            pages = context.pages
            if pages:
                page = pages[0]
                for extra_page in pages[1:]:
                    await extra_page.close()
            else:
                page = await context.new_page()
            
            await page.goto(URL)
            state = await determine_auth_state(page)
            if state == "logged_in":
                print("Already logged in.")
            else:
                error_message = None
                while True:
                    username, password =  get_credentials(error_message)
                    if not username or not password:
                        raise Exception("Login cancelled by user")

                    await login(page, username, password)

                    if await fail_log_in(page):
                        error_message = "Wrong email or password. Please try again."
                        continue
                    break

            await page.get_by_role("button", name="Got it!").click()
            await page.locator(".pi").first.click()
        
        finally:
            await context.close()


def main():
    itns = read_itns_from_csv()
    asyncio.run(run_playwright(itns))

if __name__ == "__main__":
    main()