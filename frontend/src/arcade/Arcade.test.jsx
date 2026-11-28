import React from 'react';
import {render,screen,fireEvent,waitFor,cleanup,act} from '@testing-library/react';
import {beforeEach,afterEach,it,expect,vi} from 'vitest';
import Arcade from './Arcade';
const shared=vi.hoisted(()=>({session:{user:{id:'alice'},access_token:'test-access'},settings:{das_ms:200,arr_ms:35,controls:{},sound:true,opponent_level:0,frame_rate:60},
 controls:{game:'sprint',binding:{keys:{left:'KeyJ',right:'KeyL',soft:'KeyK'},pad:{left:14}},actions:[{id:'left',name:'Move left',game_key:'ArrowLeft'},{id:'cw',name:'Rotate right',game_key:'KeyX'}]},bundle:{installed:true,can_install:false}}));
vi.mock('../contexts/SupabaseContext',()=>({useSupabase:()=>({supabase:{
 auth:{getSession:async()=>({data:{session:shared.session}}),
 onAuthStateChange:()=>({data:{subscription:{unsubscribe(){}}}}), signInWithOAuth:vi.fn()}
}})}));
vi.mock('../api',()=>({getUrl:()=> 'http://localhost:8000'}));
beforeEach(()=>{
 shared.bundle={installed:true,can_install:false};
 shared.session={user:{id:'alice'},access_token:'test-access'};
 vi.stubGlobal('fetch',vi.fn(async(url,options={})=>({ok:true,json:async()=>{
  if(url.endsWith('/runs'))return [];
  if(url.endsWith('/controls'))return shared.controls;
  if(url.endsWith('/package')) {if(options.method==='POST')shared.bundle={installed:true,can_install:true};return shared.bundle;}
  if(url.endsWith('/sessions'))return {id:'launch-1'};
  if(options.method==='PUT')return JSON.parse(options.body);
  return shared.settings;
 }})));
});
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
it('loads server settings and saves the selected handling values',async()=>{
 render(<Arcade/>);
 const das=await screen.findByLabelText('DAS');
 expect(das.value).toBe('200');
 expect(screen.getByLabelText('Frame rate').value).toBe('60');
 fireEvent.change(das,{target:{value:'150'}});
 fireEvent.click(screen.getByRole('button',{name:'Save settings'}));
 await screen.findByText('Saved');
 const save=fetch.mock.calls.find(([,options])=>options.method==='PUT');
 expect(JSON.parse(save[1].body).das_ms).toBe(150);
 expect(save[1].headers.Authorization).toBe('Bearer test-access');
});
it('saves a WASD preset for this game with the profile',async()=>{
 render(<Arcade/>);
 const preset=await screen.findByLabelText('Keyboard preset');
 expect(preset.value).toBe('hhkb');
 fireEvent.change(preset,{target:{value:'wasd'}});
 expect(screen.getByRole('button',{name:'Extra key for Move left'})).toHaveTextContent('A');
 fireEvent.click(screen.getByRole('button',{name:'Save settings'}));
 await screen.findByText('Saved');
 const save=fetch.mock.calls.find(([,options])=>options.method==='PUT');
 expect(JSON.parse(save[1].body).controls).toEqual({sprint:{keys:{left:'KeyA',right:'KeyD',soft:'KeyS',hard:'KeyW'},pad:{left:14}}});
});
it('saves settings before creating an isolated game frame',async()=>{
 render(<Arcade/>);
 fireEvent.click(await screen.findByRole('button',{name:'Play'}));
 await waitFor(()=>expect(screen.getByTitle('Sprint game')).toBeInTheDocument());
 expect(screen.getByTitle('Sprint game').src).toBe('http://localhost:8000/arcade/frame');
 expect(screen.getByTitle('Sprint game').getAttribute('allow')).toContain('gamepad');
 expect(fetch.mock.calls.filter(([,options])=>options.method!=='GET').map(([url])=>url.split('/').pop())).toEqual(['profile','sessions']);
});

it('lets a Commons admin import a package before enabling play',async()=>{
 shared.bundle={installed:false,can_install:true};
 render(<Arcade/>);
 const upload=await screen.findByLabelText('Install game package');
 expect(screen.getByRole('button',{name:'Play'})).toBeDisabled();
 const file=new File(['private package'],'game.tar.gz',{type:'application/gzip'});
 fireEvent.change(upload,{target:{files:[file]}});
 await waitFor(()=>expect(screen.getByRole('button',{name:'Play'})).toBeEnabled());
 const call=fetch.mock.calls.find(([url,options])=>url.endsWith('/package')&&options.method==='POST');
 expect(call[1].body).toBe(file);
 expect(call[1].headers.Authorization).toBe('Bearer test-access');
});

function result(source, origin='http://localhost:8000') {
 fireEvent(window,new MessageEvent('message',{origin,source,data:{type:'arcade-result'}}));
}
it('offers a focused replay action after the current game ends and replaces its frame',async()=>{
 let launches=0;
 fetch.mockImplementation(async(url,options={})=>({ok:true,json:async()=>{
  if(url.endsWith('/runs'))return [];
  if(url.endsWith('/controls'))return shared.controls;
  if(url.endsWith('/package'))return shared.bundle;
  if(url.endsWith('/sessions'))return {id:'launch-'+(++launches)};
  if(options.method==='PUT')return JSON.parse(options.body);
  return shared.settings;
 }}));
 render(<Arcade/>);
 fireEvent.click(await screen.findByRole('button',{name:'Play'}));
 const first=await screen.findByTitle('Sprint game');
 result(first.contentWindow,'https://untrusted.example');
 result(window);
 expect(screen.queryByRole('button',{name:'Play again'})).not.toBeInTheDocument();
 result(first.contentWindow);
 const replay=await screen.findByRole('button',{name:'Play again'});
 expect(replay).toHaveFocus();
 fireEvent.click(replay);
 await waitFor(()=>expect(screen.queryByRole('region',{name:'Run finished'})).not.toBeInTheDocument());
 expect(screen.getByTitle('Sprint game')).not.toBe(first);
 expect(launches).toBe(2);
 expect(fetch.mock.calls.filter(([url,options])=>url.endsWith('/profile')&&options.method==='PUT')).toHaveLength(2);
});
it('keeps the finished game available for retry when a restart fails',async()=>{
 render(<Arcade/>);
 fireEvent.click(await screen.findByRole('button',{name:'Play'}));
 result((await screen.findByTitle('Sprint game')).contentWindow);
 const replay=await screen.findByRole('button',{name:'Play again'});
 fetch.mockRejectedValueOnce(new Error('Connection lost'));
 fireEvent.click(replay);
 expect(await screen.findByRole('alert')).toHaveTextContent('Connection lost');
 expect(replay).toBeEnabled();
 expect(screen.getByRole('region',{name:'Run finished'})).toBeInTheDocument();
});
it('creates only one restart while a session request is pending',async()=>{
 render(<Arcade/>);
 fireEvent.click(await screen.findByRole('button',{name:'Play'}));
 result((await screen.findByTitle('Sprint game')).contentWindow);
 const replay=await screen.findByRole('button',{name:'Play again'});
 let resolveSave;
 fetch.mockImplementationOnce(()=>new Promise(resolve=>{resolveSave=resolve;}));
 fireEvent.click(replay); fireEvent.click(replay);
 expect(replay).toBeDisabled();
 await waitFor(()=>expect(fetch.mock.calls.filter(([,options])=>options.method==='PUT')).toHaveLength(2));
 await act(async()=>resolveSave({ok:true,json:async()=>shared.settings}));
 await waitFor(()=>expect(screen.queryByRole('region',{name:'Run finished'})).not.toBeInTheDocument());
 expect(fetch.mock.calls.filter(([url])=>url.endsWith('/sessions'))).toHaveLength(2);
});
it('embeds the separate player origin the server names and trusts only its messages',async()=>{
 fetch.mockImplementation(async(url,options={})=>({ok:true,json:async()=>{
  if(url.endsWith('/runs'))return [];
  if(url.endsWith('/package'))return shared.bundle;
  if(url.endsWith('/sessions'))return {id:'launch-1',trusted:false,frame:'https://play.example.test/arcade/frame'};
  if(options.method==='PUT')return JSON.parse(options.body);
  return shared.settings;
 }}));
 render(<Arcade/>);
 fireEvent.click(await screen.findByRole('button',{name:'Play'}));
 const frame=await screen.findByTitle('Sprint game');
 expect(frame.src).toBe('https://play.example.test/arcade/frame');
 result(frame.contentWindow,'http://localhost:8000');
 expect(screen.queryByRole('button',{name:'Play again'})).not.toBeInTheDocument();
 result(frame.contentWindow,'https://play.example.test');
 expect(await screen.findByRole('button',{name:'Play again'})).toBeInTheDocument();
});
