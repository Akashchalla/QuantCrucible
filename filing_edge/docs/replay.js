'use strict';
window.replayRequest=async function(path,body){const d=window.FILING_REPLAY;
 if(path==='state')return structuredClone(d.state);
 if(path==='database'){return {...d.database,source:'Saved Tiger Data continuous-aggregate response'};}
 if(path==='briefing'){const r=d.state.reports[body.kind],a=r&&d.voices[r.run_id];if(!a)throw Error('This window has no saved audio. Generate it in the authenticated app.');return a;}
 if(path==='explain'){const e=d.explanations[body.id];if(!e)throw Error('No saved Gemini explanation for this filing. Try one of the first three filings, or run the authenticated app.');return e;}
 if(path==='capital'){const {account,spot,strike,premium,allocation}=body,fee=.65;
  if(![account,spot,strike,premium,allocation].every(Number.isFinite)||Math.min(account,spot,strike)<=0||premium<0||premium>=strike||allocation<=0||allocation>1)throw Error('Enter positive finite inputs and a valid allocation.');
  const contracts=Math.floor(account*allocation/(100*strike+fee)),collateral=contracts*100*strike;
  return {contracts,collateral,premium_received:contracts*100*premium,breakeven:strike-premium+fee/100,max_loss:contracts*(100*(strike-premium)+fee),scenarios:[-1,-.5,-.3,-.2,-.1,-.05,0,.1,.2].map(move=>{const terminal=spot*(1+move),pnl=contracts*(100*(premium-Math.max(strike-terminal,0))-fee);return {move,terminal,pnl,account_return:pnl/account}}),note:'Hypothetical expiry payoffs calculated locally; entry fee only. No live data or orders.'};
 }
 throw Error('This is a saved replay. Run the authenticated Python app for live API operations.');
};
