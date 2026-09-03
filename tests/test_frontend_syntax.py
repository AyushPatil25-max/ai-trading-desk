import os
import unittest
import subprocess
from bs4 import BeautifulSoup
from pathlib import Path

class TestFrontendSyntax(unittest.TestCase):
    def test_index_html_javascript_syntax_braces(self):
        """
        Regression test: Ensure all <script> blocks in frontend/index.html 
        have balanced curly braces to prevent UI lockups due to SyntaxError.
        """
        frontend_path = Path(__file__).parent.parent / 'frontend' / 'index.html'
        self.assertTrue(frontend_path.exists(), "frontend/index.html should exist")

        with open(frontend_path, 'r', encoding='utf-8') as f:
            soup = BeautifulSoup(f, 'html.parser')
            
        scripts = soup.find_all('script')
        
        for idx, script in enumerate(scripts):
            if not script.string:
                continue
                
            text = script.string
            open_braces = text.count('{')
            close_braces = text.count('}')
            
            # They must be exactly balanced unless string literals contain unmatched braces.
            # In our current codebase, they should balance perfectly.
            self.assertEqual(
                open_braces, 
                close_braces, 
                f"Unbalanced braces in script {idx}. Open: {open_braces}, Close: {close_braces}. "
                "This indicates a severe SyntaxError preventing the UI from rendering."
            )
