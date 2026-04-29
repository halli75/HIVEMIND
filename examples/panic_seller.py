from hivemind_sdk import AgentArchetype, SwarmEngine, ScenarioInjector


class PanicSeller(AgentArchetype):
    archetype_name = "panic_seller"

    def decide(self, market_state, memory) -> dict:
        if market_state["price_delta_pct"] < -0.05:
            return {"action": "SELL", "amount": memory["portfolio"] * 0.5}
        return {"action": "HOLD"}

    def heuristic(self, market_state, memory) -> dict:
        if market_state["price_delta_pct"] < -0.10:
            return {"action": "SELL", "amount": memory["portfolio"] * 0.3}
        return {"action": "HOLD"}


engine = SwarmEngine(archetypes=[PanicSeller], count=100)
injector = ScenarioInjector(engine)
engine.run()
injector.inject("20% ETH price drop over 4 hours")
