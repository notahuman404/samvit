import sqlite3
import dataclasses
import enum
import time
import asyncio
import re
from typing import List, Dict, Any, Optional, Callable, Awaitable
import httpx

# --- Re-using & Extending Models from your context ---

@dataclasses.dataclass
class ComponentRequirements:
    category: str
    voltage_min: Optional[float] = None
    voltage_max: Optional[float] = None
    current_min_ma: Optional[float] = None
    max_cost_usd: Optional[float] = None
    preferred_package: Optional[str] = None

@dataclasses.dataclass
class ComponentCandidate:
    part_number: str
    manufacturer: str
    category: str
    source: str  # "offline_db" or "online_api"
    voltage_raw: str
    current_raw: str
    package: Optional[str] = None
    cost_usd: float = 0.0
    confidence_score: float = 0.0
    notes: str = ""
    source_url: Optional[str] = None

# --- Existing Models for Web Connector Compatibility ---
@dataclasses.dataclass
class WebSearchConnectorInput:
    category: str
    requirements: Dict[str, Any] = dataclasses.field(default_factory=dict)
    keywords: List[str] = dataclasses.field(default_factory=list)
    constraints: Dict[str, Any] = dataclasses.field(default_factory=dict)

@dataclasses.dataclass
class CandidateComponent:
    part_number: str
    manufacturer: str
    source_url: str
    datasheet_url: Optional[str] = None
    package: Optional[str] = None
    category: Optional[str] = None
    confidence: float = 0.0
    retrieval_method: str = ""

@dataclasses.dataclass
class WebSearchConnectorOutput:
    query: str
    candidates: List[CandidateComponent] = dataclasses.field(default_factory=list)
    search_metadata: Dict[str, Any] = dataclasses.field(default_factory=dict)

# --- Parsing Helpers for Offline DB ---

def parse_voltage_range(v_str: str) -> tuple[float, float]:
    """Extracts (min_v, max_v) from strings like '3.3-5V', '5V/3.3V', or '3.7V nominal'"""
    if not v_str or v_str == "—":
        return 0.0, float('inf')
    
    # Strip units
    clean = v_str.upper().replace("V", "").replace("NOMINAL", "").strip()
    
    # Handle ranges like 3.3-5
    if "-" in clean:
        try:
            parts = clean.split("-")
            return float(parts[0]), float(parts[1])
        except ValueError:
            pass
    # Handle options like 5/3.3
    if "/" in clean:
        try:
            parts = [float(p) for p in clean.split("/")]
            return min(parts), max(parts)
        except ValueError:
            pass
    
    # Single value
    try:
        val = float(clean)
        return val, val
    except ValueError:
        return 0.0, float('inf')

def parse_current_ma(c_str: str) -> float:
    """Extracts numeric mA value from text like '3000mAh', '0.6', or '1000'"""
    if not c_str or c_str == "—":
        return 0.0
    clean = c_str.lower().replace("mah", "").replace("ma", "").strip()
    try:
        return float(clean)
    except ValueError:
        return 0.0

# --- Existing Mock Web Connector ---

class InMemoryCache:
    def __init__(self): self._cache = {}
    def get(self, key: str): return self._cache.get(key)
    def set(self, key: str, val: Any): self._cache[key] = val

class DigiKeyProvider:
    def __init__(self, cache): self.cache = cache
    async def search(self, query: WebSearchConnectorInput) -> WebSearchConnectorOutput:
        # Mock online return if keys are missing to illustrate system fallback flow
        print(f"   [Online API] Searching DigiKey for online candidates matching '{query.category}'...")
        await asyncio.sleep(0.5) 
        return WebSearchConnectorOutput(
            query=query.category,
            candidates=[
                CandidateComponent(
                    part_number="TPS63020I-ONLINE", 
                    manufacturer="Texas Instruments", 
                    source_url="https://digikey.com/shorturl",
                    package="VSON-10",
                    category=query.category,
                    confidence=0.95
                )
            ]
        )

# --- Core Selection Engine ---

class PartSelectionEngine:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.cache = InMemoryCache()
        self.online_provider = DigiKeyProvider(self.cache)

    def _query_offline_db(self, category: str) -> List[ComponentCandidate]:
        """Queries the SQLite database for matches based on category strings."""
        candidates = []
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            
            # Using partial matches for flexibility (e.g., 'IMU', 'Buck-Boost')
            c.execute("SELECT name, category, description, voltage_v, current_ma, package, cost_usd, notes FROM parts WHERE category LIKE ?", (f"%{category}%",))
            rows = c.fetchall()
            
            for row in rows:
                candidates.append(ComponentCandidate(
                    part_number=row[0],
                    manufacturer="Unknown/Generic", # Extracted from name if needed
                    category=row[1],
                    source="offline_db",
                    voltage_raw=row[3],
                    current_raw=row[4],
                    package=row[5],
                    cost_usd=float(row[6]),
                    notes=row[7]
                ))
            conn.close()
        except sqlite3.OperationalError as e:
            print(f"Offline DB warning: {e}. Ensure the database is built and located at {self.db_path}")
        return candidates

    def _score_candidate(self, candidate: ComponentCandidate, reqs: ComponentRequirements) -> float:
        """
        Calculates compatibility score. 
        Returns -1.0 if any hard constraints are violated.
        """
        score = 100.0
        
        # 1. Voltage Constraint check
        cand_min_v, cand_max_v = parse_voltage_range(candidate.voltage_raw)
        if reqs.voltage_min is not None and cand_max_v < reqs.voltage_min:
            return -1.0  # Hard penalty: Under-voltage rating
        if reqs.voltage_max is not None and cand_min_v > reqs.voltage_max:
            return -1.0  # Hard penalty: Incompatible voltage limits

        # 2. Current Capacity check
        cand_ma = parse_current_ma(candidate.current_raw)
        if reqs.current_min_ma is not None and cand_ma < reqs.current_min_ma and cand_ma > 0:
            return -1.0  # Hard penalty: Cannot provide/handle required current

        # 3. Cost Penalty (Lower cost is better)
        if reqs.max_cost_usd is not None and candidate.cost_usd > reqs.max_cost_usd:
            return -1.0  # Hard penalty: Over budget
        score -= (candidate.cost_usd * 2.0)  # Moderate deduction for higher cost

        # 4. Package Preference bonus
        if reqs.preferred_package and candidate.package:
            if reqs.preferred_package.lower() in candidate.package.lower():
                score += 15.0  # Preference reward

        return max(score, 0.0)

    async def select_best_part(self, reqs: ComponentRequirements) -> Optional[ComponentCandidate]:
        print(f"\n[Engine] Starting evaluation for subsystem tier: '{reqs.category}'")
        
        # Step 1: Query Offline Database First
        print(f" -> Querying local offline inventory DB...")
        offline_candidates = self._query_offline_db(reqs.category)
        
        scored_offline = []
        for cand in offline_candidates:
            score = self._score_candidate(cand, reqs)
            if score >= 0:  # Kept if constraints passed
                cand.confidence_score = score
                scored_offline.append(cand)
                
        # Sort local parts by highest compatibility score
        scored_offline.sort(key=lambda x: x.confidence_score, reverse=True)
        
        if scored_offline:
            best_local = scored_offline[0]
            print(f" -> Found matching offline component: {best_local.part_number} (Score: {best_local.confidence_score:.2f})")
            return best_local

        # Step 2: Fallback to Online Web Connector if local check yields 0 matches
        print(f" -> No suitable local components found. Falling back to Online API lookup...")
        
        web_input = WebSearchConnectorInput(
            category=reqs.category,
            requirements={
                "voltage_min": reqs.voltage_min,
                "voltage_max": reqs.voltage_max,
                "current_min": reqs.current_min_ma
            }
        )
        
        try:
            online_response = await self.online_provider.search(web_input)
            if online_response.candidates:
                # Turn the online match structure into a standard Engine candidate
                best_online = online_response.candidates[0]
                return ComponentCandidate(
                    part_number=best_online.part_number,
                    manufacturer=best_online.manufacturer,
                    category=best_online.category or reqs.category,
                    source="online_api",
                    voltage_raw=f"{reqs.voltage_min or ''}-{reqs.voltage_max or ''}V",
                    current_raw=f"{reqs.current_min_ma or ''}mA",
                    package=best_online.package,
                    cost_usd=0.0, # Determine via active parsing in production API
                    confidence_score=best_online.confidence * 100,
                    source_url=best_online.source_url
                )
        except Exception as e:
            print(f" -> Online lookup failed or timed out: {e}")
            
        print(f" -> [Alert] No component matches could be resolved offline or online.")
        return None

# --- Verification & Execution Routine ---

async def main():
    engine = PartSelectionEngine("./samvit_parts.db")
    
    # Test Scenario A: Component exists offline & matches rules perfectly
    reqs_a = ComponentRequirements(
        category="Buck-Boost",
        voltage_min=3.3,
        voltage_max=5.0,
        current_min_ma=1500,
        preferred_package="VSON-10"
    )
    part_a = await engine.select_best_part(reqs_a)
    print(f"Result A: Selected {part_a.part_number if part_a else 'None'} from {part_a.source if part_a else 'N/A'}")

    # Test Scenario B: Subsystem Category does not exist offline -> Expect Online Fallback
    reqs_b = ComponentRequirements(
        category="FPGA-Processor",
        voltage_min=1.2,
        voltage_max=3.3,
        current_min_ma=500
    )
    part_b = await engine.select_best_part(reqs_b)
    print(f"Result B: Selected {part_b.part_number if part_b else 'None'} from {part_b.source if part_b else 'N/A'}")

if __name__ == "__main__":
    asyncio.run(main())