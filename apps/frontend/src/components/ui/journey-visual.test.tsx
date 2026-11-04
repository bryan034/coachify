import {fireEvent,render,screen} from '@testing-library/react';
import {expect,it} from 'vitest';
import {JourneyVisual} from './journey-visual';
it('stays still by default',()=>{
 const {container}=render(<JourneyVisual/>);
 expect(container.querySelector('.journey-visual')).not.toHaveClass('is-animated');
 expect(screen.queryByRole('button')).not.toBeInTheDocument();
});
it('animates one ball across three platforms, and can be paused and resumed',()=>{
 const {container}=render(<JourneyVisual animated/>);
 const visual=container.querySelector('.journey-visual')!;
 expect(visual).toHaveClass('is-animated');
 expect(container.querySelectorAll('.jv-ball')).toHaveLength(1);
 for(const platform of ['.jv-platform-1','.jv-platform-2','.jv-platform-3'])expect(container.querySelector(platform)).toBeInTheDocument();
 expect(container.querySelector('svg')).toHaveAttribute('aria-hidden','true');
 fireEvent.click(screen.getByRole('button',{name:'Pause animation'}));
 expect(visual).toHaveClass('is-paused');
 fireEvent.click(screen.getByRole('button',{name:'Play animation'}));
 expect(visual).not.toHaveClass('is-paused');
});
