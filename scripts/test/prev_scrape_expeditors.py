import asyncio
from pathlib import Path
import os

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError


# track num example: X20260107452391 X20260107452391 X20260113797628

URL = "https://go2expo.expeditors.com/dashboard"

EDGE_USER_DATA_DIR = (
    Path(os.environ["LOCALAPPDATA"])
    / "Google"
    / "Chrome"
    / "User Data"
)


async def install_pdf_blob_capture_hook(page):
    """
    Installs a browser-side hook that captures PDF blobs created through URL.createObjectURL.
    This should be installed before the action that causes PDFs to be generated.
    """
    await page.evaluate("""
        () => {
            window.__capturedPdfBlobs = [];
            window.__capturedPdfBlobPromises = [];

            if (window.__pdfBlobCaptureInstalled) {
                return;
            }

            window.__pdfBlobCaptureInstalled = true;

            const originalCreateObjectURL = URL.createObjectURL.bind(URL);

            URL.createObjectURL = function(obj) {
                const url = originalCreateObjectURL(obj);

                if (obj instanceof Blob) {
                    const type = (obj.type || "").toLowerCase();

                    if (type.includes("pdf")) {
                        const promise = obj.arrayBuffer().then(buffer => {
                            window.__capturedPdfBlobs.push({
                                url,
                                type: obj.type,
                                size: obj.size,
                                bytes: Array.from(new Uint8Array(buffer))
                            });
                        });

                        window.__capturedPdfBlobPromises.push(promise);
                    }
                }

                return url;
            };
        }
    """)


async def clear_captured_pdf_blobs(page):
    """
    Clears previously captured PDF blobs while keeping the hook installed.
    """
    await page.evaluate("""
        () => {
            window.__capturedPdfBlobs = [];
            window.__capturedPdfBlobPromises = [];
        }
    """)


async def capture_and_save_blob_pdfs(page, output_dir: Path, tracking_number: str):
    """
    Clicks the View button, captures generated PDF blobs, and saves them locally.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    await clear_captured_pdf_blobs(page)

    print("Clicking View to generate PDF blobs...")

    view_button = page.get_by_role("button", name="View")

    await view_button.wait_for(state="visible", timeout=15000)
    await view_button.click()

    # Give the site time to generate blobs.
    await page.wait_for_timeout(5000)

    blobs = await page.evaluate("""
        async () => {
            await Promise.all(window.__capturedPdfBlobPromises || []);
            return window.__capturedPdfBlobs || [];
        }
    """)

    print(f"Captured PDF blobs: {len(blobs)}")

    saved = []

    for i, blob in enumerate(blobs, start=1):
        pdf_bytes = bytes(blob["bytes"])

        if not pdf_bytes.startswith(b"%PDF"):
            print(f"Warning: captured blob {i} does not start with %PDF")

        output_path = output_dir / f"{tracking_number}_document_{i}.pdf"
        output_path.write_bytes(pdf_bytes)

        print(
            f"Saved {output_path.resolve()} "
            f"| bytes={len(pdf_bytes)} "
            f"| starts_pdf={pdf_bytes.startswith(b'%PDF')}"
        )

        saved.append(output_path)

    if not saved:
        raise RuntimeError(
            "No PDF blobs captured. The site may not be using URL.createObjectURL for PDFs, "
            "or the PDF may have been generated before the capture hook was installed."
        )

    return saved


async def open_declarations_tracking_search(page):
    """
    Opens the Declarations option from the tracking dropdown.
    """
    await page.locator("#pn_id_24").get_by_role(
        "button",
        name="dropdown trigger"
    ).click()

    await page.get_by_text("Declarations", exact=True).click()


async def submit_tracking_number(page, tracking_number: str):
    """
    Enters and submits the tracking number.
    """
    tracking_input = page.locator("#actionboxInputTrack").get_by_role("textbox")

    await tracking_input.wait_for(state="visible", timeout=15000)
    await tracking_input.click()
    await tracking_input.fill(tracking_number)

    await page.locator("#track-your-shipment-widget #expo-shared-button").click()


async def is_tracking_number_invalid(page) -> bool:
    """
    Tries to detect whether the submitted tracking number was invalid.

    You may need to adjust these selectors/texts based on the exact site messages.
    """
    invalid_indicators = [
        page.get_by_text("invalid", exact=False),
        page.get_by_text("not found", exact=False),
        page.get_by_text("No results", exact=False),
        page.get_by_text("No records", exact=False),
        page.get_by_text("Unable to find", exact=False),
    ]

    for locator in invalid_indicators:
        try:
            await locator.first.wait_for(state="visible", timeout=2000)
            return True
        except PlaywrightTimeoutError:
            pass

    return False


async def wait_for_valid_tracking_result(page):
    """
    Waits for either a Documents link or an invalid tracking result.
    Returns True if valid, False if invalid.
    """
    documents_link = page.get_by_role("link", name="Documents")

    try:
        await documents_link.wait_for(state="visible", timeout=10000)
        return True
    except PlaywrightTimeoutError:
        return not await is_tracking_number_invalid(page)


async def get_valid_tracking_number_from_user(page):
    """
    Keeps asking for tracking numbers until the site appears to accept one.
    """
    while True:
        tracking_number = await asyncio.to_thread(
            input,
            "\nEnter a tracking number: "
        )

        tracking_number = tracking_number.strip()

        if not tracking_number:
            print("Tracking number cannot be empty.")
            continue

        print(f"Submitting tracking number: {tracking_number}")

        await submit_tracking_number(page, tracking_number)

        is_valid = await wait_for_valid_tracking_result(page)

        if is_valid:
            print(f"Tracking number accepted: {tracking_number}")
            return tracking_number

        print(f"Tracking number appears invalid: {tracking_number}")
        print("Please try again.")


async def open_documents_page(page):
    """
    Opens the Documents tab/link.
    """
    documents_link = page.get_by_role("link", name="Documents")
    await documents_link.wait_for(state="visible", timeout=15000)
    await documents_link.click()

    print("Opened Documents page.")


async def select_all_document_checkboxes(page):
    """
    Selects all enabled document checkboxes.
    """
    checkboxes = page.locator(
        "tr .checkbox-field p-tablecheckbox .p-checkbox .p-checkbox-input"
    )

    await checkboxes.first.wait_for(state="visible", timeout=15000)

    count = await checkboxes.count()
    print(f"Found {count} document checkbox(es).")

    selected_count = 0

    for i in range(count):
        cb = checkboxes.nth(i)

        if await cb.is_enabled():
            checked = await cb.is_checked()

            if not checked:
                await cb.click()

            selected_count += 1

    print(f"Selected {selected_count} document checkbox(es).")

    if selected_count == 0:
        raise RuntimeError("No enabled document checkboxes were found.")


async def process_documents(page, tracking_number):
    """
    Replace this with your actual document-processing logic.
    If your real process_documents is already defined elsewhere, remove this placeholder.
    """
    print(f"Processing documents for tracking number: {tracking_number}")
    # Your real processing logic goes here.


async def run_single_tracking_number_workflow(page, output_root: Path):
    """
    Runs the complete workflow for one valid tracking number.
    """
    tracking_number = await get_valid_tracking_number_from_user(page)

    # Install the hook before opening Documents/selecting/checking/viewing.
    await install_pdf_blob_capture_hook(page)

    await open_documents_page(page)

    await select_all_document_checkboxes(page)

    output_dir = output_root / tracking_number

    saved_files = await capture_and_save_blob_pdfs(
        page=page,
        output_dir=output_dir,
        tracking_number=tracking_number,
    )

    print(f"Saved {len(saved_files)} PDF file(s).")

    await process_documents(page, tracking_number)

    print("Ready for next tracking number.\n")


async def run_playwright():
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=EDGE_USER_DATA_DIR,
            channel="msedge",
            headless=False,
            slow_mo=100,
            accept_downloads=True,
            no_viewport=False,
            permissions=["clipboard-read", "clipboard-write"],
        )

        try:
            page = context.pages[0] if context.pages else await context.new_page()

            await page.goto(URL)

            await asyncio.to_thread(
                input,
                "\nEnsure you are logged in and press Enter..."
            )

            await open_declarations_tracking_search(page)

            output_root = Path.cwd() / "outputs"

            while True:
                try:
                    await run_single_tracking_number_workflow(page, output_root)
                except Exception as e:
                    print(f"Workflow failed: {type(e).__name__}: {e}")

                again = await asyncio.to_thread(
                    input,
                    "Press Enter to process another tracking number, or type q to quit: "
                )

                if again.strip().lower() in {"q", "quit", "exit"}:
                    break

                # Optional: navigate back to dashboard or reopen Declarations search if needed.
                await page.goto(URL)
                await open_declarations_tracking_search(page)

            await page.pause()

        finally:
            await context.close()


def main():
    asyncio.run(run_playwright())


if __name__ == "__main__":
    main()