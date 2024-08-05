#!/usr/bin/env python3
"""
A script to scrape audiobook data and download audiobooks from the Kubus Storytell website.

Requirements:
- requests
- beautifulsoup4
- mutagen
"""

import logging
import re
from pathlib import Path
from typing import Dict, List, Optional
from bs4 import BeautifulSoup
import requests
from mutagen.id3 import ID3, ID3NoHeaderError, APIC, TIT2, TALB

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


class AudiobookScraper:
    """Class to scrape audiobook data from a website."""

    def __init__(self, url: str, headers: Dict[str, str], audio_fetch_template: str):
        self.url = url
        self.headers = headers
        self.audio_fetch_template = audio_fetch_template
        logging.info(f"AudiobookScraper initialized with URL: {url}")

    def fetch_page(self) -> BeautifulSoup:
        logging.info(f"Fetching page content from URL: {self.url}")
        try:
            response = requests.get(self.url, headers=self.headers)
            response.raise_for_status()
            logging.info("Page content fetched successfully")
            return BeautifulSoup(response.content, 'html.parser')
        except requests.RequestException as e:
            logging.error(f"Failed to fetch page content: {e}")
            raise

    def extract_audiobook_data(self, soup: BeautifulSoup) -> List[Dict[str, str]]:
        logging.info("Extracting audiobook data")
        audiobooks = []
        for div in soup.find_all('div', class_=re.compile(r'\baudiobook\b')):
            data_id = div.get('data-id')
            title_div = div.find('div', class_='title')
            title = title_div.get_text(strip=True) if title_div else None
            cover_url = self.extract_image_url(div.find('div', class_='cover lazyBackgroundNone'))
            audio_link = self.get_audio_src(data_id) if data_id else None

            if not title or not data_id:
                logging.warning(f"Skipping audiobook with missing title or data-id: {data_id}")
                continue

            audiobooks.append({
                'title': title,
                'cover_link': cover_url,
                'audio_link': audio_link,
            })

        logging.info(f"Extracted {len(audiobooks)} audiobooks")
        return audiobooks

    def get_audio_src(self, data_id: str) -> Optional[str]:
        url = self.audio_fetch_template.format(data_id=data_id)
        try:
            logging.info(f"Fetching audio source from URL: {url}")
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
            source_tag = soup.find('source', {'type': 'audio/mpeg'})
            return source_tag['src'] if source_tag and 'src' in source_tag.attrs else None
        except requests.RequestException as e:
            logging.error(f"Failed to fetch audio source: {e}")
            return None

    def extract_image_url(self, cover_div) -> Optional[str]:
        if cover_div and 'style' in cover_div.attrs:
            match = re.search(r'background-image:\s*url\(([^)]+)\)', cover_div['style'])
            return match.group(1) if match else None
        logging.warning("Cover attribute not found or URL not in style attribute.")
        return None

    def run(self) -> List[Dict[str, str]]:
        try:
            soup = self.fetch_page()
            return self.extract_audiobook_data(soup)
        except Exception as e:
            logging.error(f"An error occurred during the scraping process: {e}")
            return []


class FileManager:
    """Class to handle file operations like downloading and setting metadata."""

    @staticmethod
    def download_file(url: str, file_path: Path, chunk_size: int = 8192) -> None:
        logging.info(f"Downloading file from URL: {url} to path: {file_path}")
        try:
            response = requests.get(url, stream=True)
            response.raise_for_status()
            with file_path.open('wb') as file:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    file.write(chunk)
            logging.info(f"File downloaded successfully to: {file_path}")
        except requests.RequestException as e:
            logging.error(f"Failed to download file: {e}")
            raise

    @staticmethod
    def download_mp3(url: str, destination_path: Path, max_retries: int = 3) -> None:
        attempt = 0
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.85 Safari/537.36',
            'Accept': 'audio/mpeg, audio/*; q=0.9',
        }

        while attempt < max_retries:
            try:
                logging.info(f"Attempting to download MP3 file from URL: {url} (Attempt {attempt + 1})")
                response = requests.get(url, stream=True, headers=headers, allow_redirects=True)
                response.raise_for_status()
                
                if not response.content:
                    raise ValueError("No content received from the URL.")
                
                with destination_path.open('wb') as file:
                    for chunk in response.iter_content(chunk_size=8192):
                        file.write(chunk)
                
                if destination_path.stat().st_size == 0:
                    raise ValueError("Downloaded file is empty.")
                
                logging.info(f"MP3 file successfully downloaded to: {destination_path}")
                return
            except (requests.RequestException, ValueError) as e:
                logging.warning(f"Attempt {attempt + 1} failed: {e}")
                attempt += 1
        
        logging.error(f"Failed to download the MP3 file after {max_retries} attempts.")
        raise ValueError("Max retries exceeded")

    @staticmethod
    def set_mp3_metadata(mp3_path: Path, audio_name: str, album_name: str, cover_path: Path) -> None:
        try:
            audio = ID3(mp3_path)
        except ID3NoHeaderError:
            audio = ID3()

        audio.add(TIT2(encoding=3, text=audio_name))
        audio.add(TALB(encoding=3, text=album_name))
        with cover_path.open('rb') as cover_file:
            audio.add(
                APIC(
                    encoding=3,
                    mime='image/jpeg',
                    type=3,
                    desc='Cover',
                    data=cover_file.read(),
                )
            )

        audio.save(mp3_path)
        logging.info(f"Metadata set for MP3 file: {mp3_path}")


class AudiobookProcessor:
    """Class to manage the processing of audiobook files including downloading and setting metadata."""

    def __init__(self, audio_name: str, cover_link: str, audio_link: str, album_name: str, destination: Path):
        self.audio_name = audio_name
        self.cover_link = cover_link
        self.audio_link = audio_link
        self.album_name = album_name
        self.folder_path = destination / audio_name
        self.cover_path = self.folder_path / 'cover.jpg'
        self.mp3_path = self.folder_path / f'{audio_name}.mp3'
        logging.info(f"AudiobookProcessor initialized for: {audio_name}")

    def process(self) -> None:
        self.folder_path.mkdir(parents=True, exist_ok=True)

        if not self.cover_path.exists():
            logging.info(f"Downloading cover image from {self.cover_link}...")
            FileManager.download_file(self.cover_link, self.cover_path)

        if not self.mp3_path.exists():
            logging.info(f"Downloading MP3 file from {self.audio_link}...")
            FileManager.download_mp3(self.audio_link, self.mp3_path)

        logging.info(f"Setting metadata for {self.mp3_path}...")
        FileManager.set_mp3_metadata(self.mp3_path, self.audio_name, self.album_name, self.cover_path)

        logging.info(f"Process completed for '{self.audio_name}'.")


def default_headers() -> Dict[str, str]:
    return {
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'accept-language': 'pl-PL,pl;q=0.8',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
    }


def main(destination: Path) -> None:
    album_name = 'Kubus Storytel'
    url = 'https://kubus.pl/audiobooki/'
    audio_fetch_template = "https://kubus.pl/?p={data_id}"
    headers = default_headers()

    scraper = AudiobookScraper(url, headers, audio_fetch_template)
    audiobooks = scraper.run()

    for audiobook in audiobooks:
        processor = AudiobookProcessor(
            audiobook['title'],
            audiobook['cover_link'],
            audiobook['audio_link'],
            album_name,
            destination,
        )
        processor.process()


if __name__ == '__main__':
    import sys

    if len(sys.argv) != 2:
        print("Usage: python script.py <destination_directory>")
        sys.exit(1)

    destination_dir = Path(sys.argv[1])
    if not destination_dir.is_dir():
        print(f"The destination path '{destination_dir}' is not a directory.")
        sys.exit(1)

    main(destination_dir)
