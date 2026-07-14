#!/usr/bin/env python3
"""
Export data from Umweltbundesamt Power BI dashboards using browser automation.
Requires: pip install playwright
Run: playwright install chromium
"""
import asyncio
import json
import os
from datetime import datetime

# Power BI report configurations
REPORTS = {
    'grundwasser': {
        'name': 'GZUEV_Grundwasser_oeffentlich',
        'url': 'https://www.umweltbundesamt.at/dashboard-grundwasser',
        'embed_url': 'https://secure.umweltbundesamt.at/powerbi-embed/start?reportName=GZUEV_Grundwasser_oeffentlich',
        'report_id': '58693000-4103-49a3-b311-dca5d162fdc6',
        'description': 'Groundwater quality monitoring data'
    },
    'fliessgewaesser': {
        'name': 'GZUEV_Fliessgewaesser_oeffentlich', 
        'url': 'https://www.umweltbundesamt.at/dashboard-fliessgewaesser-ueberwachung',
        'embed_url': 'https://secure.umweltbundesamt.at/powerbi-embed/start?reportName=GZUEV_Fliessgewaesser_oeffentlich',
        'report_id': '574b58ae-7f98-407a-af08-2a339eb9d1f4',
        'description': 'River water quality monitoring data'
    }
}

OUTPUT_DIR = '/home/exedev/austria-drought-map/data/water_quality/powerbi_exports'
os.makedirs(OUTPUT_DIR, exist_ok=True)

async def export_powerbi_report(report_key):
    """Export data from a Power BI report using Playwright"""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("Playwright not installed. Run: pip install playwright && playwright install chromium")
        return None
    
    report = REPORTS[report_key]
    print(f"Exporting: {report['name']}")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = await context.new_page()
        
        # Navigate to dashboard
        print(f"  Loading: {report['url']}")
        await page.goto(report['url'], wait_until='networkidle', timeout=60000)
        await page.wait_for_timeout(5000)  # Wait for Power BI to load
        
        # Find the Power BI iframe
        iframe = page.frame_locator('iframe').first
        
        # Try to find and click export button (Power BI has various export options)
        try:
            # Look for export/download options in the report
            export_btn = iframe.locator('[aria-label*="Export"], [title*="Export"], [data-testid*="export"]').first
            if await export_btn.is_visible():
                await export_btn.click()
                await page.wait_for_timeout(2000)
                print("  Found export button")
        except:
            print("  No direct export button found")
        
        # Take screenshot for reference
        screenshot_path = f"{OUTPUT_DIR}/{report_key}_screenshot.png"
        await page.screenshot(path=screenshot_path, full_page=True)
        print(f"  Screenshot saved: {screenshot_path}")
        
        await browser.close()
    
    return screenshot_path

def main():
    print("Power BI Data Export Script")
    print("=" * 50)
    print(f"Output directory: {OUTPUT_DIR}")
    print()
    
    # Save report metadata
    metadata = {
        'timestamp': datetime.now().isoformat(),
        'reports': REPORTS,
        'notes': [
            'Power BI embeds do not expose raw data via API',
            'Options: 1) Browser automation to navigate and export',
            '         2) Request data directly from opendata@umweltbundesamt.at',
            '         3) Use H2O Fachdatenbank: https://wasser.umweltbundesamt.at/h2odb/'
        ]
    }
    
    with open(f'{OUTPUT_DIR}/report_metadata.json', 'w') as f:
        json.dump(metadata, f, indent=2)
    print(f"Saved: {OUTPUT_DIR}/report_metadata.json")
    
    # Try to run export (requires playwright)
    try:
        for key in REPORTS:
            asyncio.run(export_powerbi_report(key))
    except Exception as e:
        print(f"Export failed: {e}")
        print("Install playwright: pip install playwright && playwright install chromium")

if __name__ == '__main__':
    main()
