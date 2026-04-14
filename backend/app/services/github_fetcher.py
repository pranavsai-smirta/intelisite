"""GitHub issue fetcher for CHR reports"""
import os
import re
from datetime import datetime
from typing import List, Optional
from dataclasses import dataclass
from github import Github
from rich.console import Console

console = Console()

@dataclass
class CHRIssue:
    """Represents a CHR report issue from GitHub"""
    repo: str
    issue_number: int
    title: str
    url: str
    body: str
    created_at: datetime
    updated_at: datetime
    client_name: str
    month: str

class GitHubFetcher:
    """Fetches CHR report issues from GitHub"""
    
    # Pattern: [NYOH] Clinic health report for [Jan 2026]
    TITLE_PATTERNS = [
        r'\[([A-Z]+)\]\s+Clinic health report for\s+\[([A-Za-z]+)\s*-?\s*(\d{4})\]',
    ]
    
    def __init__(self, github_token: str):
        self.github = Github(github_token)
        
    def fetch_chr_issues(
        self,
        repo_name: str,
        target_month: str,
        label: str = "Clinic health report"
    ) -> List[CHRIssue]:
        """Fetch CHR issues from repository"""
        console.print(f"[cyan]Fetching from {repo_name}...[/cyan]")
        
        chr_issues = []
        
        try:
            repo = self.github.get_repo(repo_name)
            issues = repo.get_issues(
                state="all",
                labels=[label],
                sort="created",
                direction="desc"
            )
            
            for issue in issues:
                parsed = self._parse_title(issue.title)
                if not parsed:
                    continue
                
                client_code, issue_month, issue_year = parsed
                
                try:
                    issue_date = datetime.strptime(f"{issue_month} {issue_year}", "%b %Y")
                except ValueError:
                    try:
                        issue_date = datetime.strptime(f"{issue_month} {issue_year}", "%B %Y")
                    except ValueError:
                        continue
                
                if issue_date.strftime("%Y-%m") != target_month:
                    continue
                
                chr_issue = CHRIssue(
                    repo=repo_name,
                    issue_number=issue.number,
                    title=issue.title,
                    url=issue.html_url,
                    body=issue.body or "",
                    created_at=issue.created_at,
                    updated_at=issue.updated_at,
                    client_name=client_code,
                    month=target_month
                )
                
                chr_issues.append(chr_issue)
                console.print(f"[green]  ✓ #{issue.number}: {client_code}[/green]")
            
            console.print(f"[bold green]✓ Found {len(chr_issues)} issues[/bold green]")
                
        except Exception as e:
            console.print(f"[red]✗ Error: {e}[/red]")
            raise
            
        return chr_issues
    
    def _parse_title(self, title: str) -> Optional[tuple]:
        """Parse title to extract client, month, year"""
        for pattern in self.TITLE_PATTERNS:
            match = re.search(pattern, title)
            if match:
                return (match.group(1), match.group(2), match.group(3))
        return None
