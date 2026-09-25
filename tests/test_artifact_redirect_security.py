import unittest
import urllib.request
from pathlib import Path

from runtime.artifact_http import SafeArtifactRedirectHandler

ROOT=Path(__file__).resolve().parents[1]

class ArtifactRedirectSecurityTests(unittest.TestCase):
    def test_cross_host_redirect_strips_github_authorization(self):
        req=urllib.request.Request(
            "https://api.github.com/repos/P00NSMASHER/portfolio-brain/actions/artifacts/1/zip",
            headers={"Authorization":"Bearer SECRET","Accept":"application/vnd.github+json"},
            method="GET",
        )
        redirected=SafeArtifactRedirectHandler().redirect_request(
            req,None,302,"Found",{},
            "https://productionresultssa0.blob.core.windows.net/actions-results/signed-token",
        )
        self.assertIsNotNone(redirected)
        self.assertIsNone(redirected.get_header("Authorization"))
        self.assertEqual(redirected.get_header("Accept"),"application/vnd.github+json")

    def test_same_host_redirect_may_keep_authorization(self):
        req=urllib.request.Request(
            "https://api.github.com/repos/P00NSMASHER/portfolio-brain/actions/artifacts/1/zip",
            headers={"Authorization":"Bearer SECRET"},
            method="GET",
        )
        redirected=SafeArtifactRedirectHandler().redirect_request(
            req,None,302,"Found",{},
            "https://api.github.com/repos/P00NSMASHER/portfolio-brain/actions/artifacts/2/zip",
        )
        self.assertEqual(redirected.get_header("Authorization"),"Bearer SECRET")

    def test_all_persistent_state_restorers_use_safe_redirect_helper(self):
        paths=[
            "runtime/artifact_state.py",
            "hunting/artifact_state.py",
            "scheduler/artifact_state.py",
            "cost_governor/artifact_state.py",
            "notifications/artifact_state.py",
        ]
        for path in paths:
            body=(ROOT/path).read_text()
            self.assertIn("from runtime.artifact_http import open_url",body,path)
            self.assertIn("open_url(",body,path)
            self.assertNotIn("urllib.request.urlopen(",body,path)

if __name__=="__main__":unittest.main()
