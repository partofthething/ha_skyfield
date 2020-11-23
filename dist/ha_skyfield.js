/* A card for the skyfield integration.
 *
 * I think perhaps we need to update the skyfield backend
 * to produce the data as a state variable, including the line
 * for the solstices and all the planets. Then we can just grab
 * that state through the state machine.
*/

//var Plotly = require('plotly-latest.min.js')
//import Plotly from '/local/plotly-latest.min.js'

import '/local/plotly.js'

class SkyfieldCard extends HTMLElement {
  set hass(hass) {
    if (!this.content) {
      const card = document.createElement('ha-card');
      card.header = 'Skyfield';
      this.content = document.createElement('div');
      this.content.style.padding = '0 16px 16px';

      const plotwin = document.createElement('div');
      var att = document.createAttribute("id");
      att.value = "plotwin";
      plotwin.setAttributeNode(att);
      this.content.appendChild(plotwin);

      card.appendChild(this.content);
      this.appendChild(card);
      this.makePlot(plotwin);
    }

    //const entityId = this.config.entity;
    //const state = hass.states[entityId];
    //const stateStr = state ? state.state : 'unavailable';

    //this.content.innerHTML = `
    //<h1>Howdy fool</h1>
    //`;
    
  }

  setConfig(config) {
  //  if (!config.entity) {
  //    throw new Error('You need to define an entity');
  //  }
    this.config = config;
  }

  // The height of your card. Home Assistant uses this to automatically
  // distribute all cards over the available columns.
  getCardSize() {
    return 3;
  }

  makePlot(plotwin) {
    var data = {
        r: [1,2,3,4,5,6],
        theta: [10,20,45,90,180,270],
        mode: 'lines',
        name: 'My data',
        marker: {
          color: 'none',
          line: {color: 'green'}
        },
        type: 'scatterpolar'
    };

    var layout = {
      autosize: false,
      width: 400,
      height: 400,
      margin: {
        l: 10,
        r: 10,
        b: 10,
        t: 10,
        pad: 2
      },
      title: 'Space status',
      font: {
        family: 'Arial, sans-serif;',
        size: 12,
        color: '#000'
      },
      showlegend: true,
      orientation: -90
    };
    Plotly.newPlot(plotwin, [data], layout);
    }
  }

customElements.define('skyfield-card', SkyfieldCard);
